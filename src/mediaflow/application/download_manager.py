"""Authoritative download lifecycle orchestration and progress policy."""

import logging
from dataclasses import dataclass
from threading import Event, RLock

from mediaflow.application.events import (
    ApplicationEvent,
    TaskFailed,
    TaskProgressChanged,
    TaskStateChanged,
)
from mediaflow.application.models import DownloadArtifact, DownloadJob, DownloadOutcome
from mediaflow.application.ports import (
    Clock,
    Downloader,
    EventPublisher,
    ProgressSink,
    TaskRepository,
)
from mediaflow.domain import (
    AttemptId,
    DownloadTask,
    Failure,
    FailureCategory,
    ProgressSnapshot,
    TaskId,
    TaskState,
    UtcTimestamp,
)

_LOGGER = logging.getLogger("mediaflow.download")


@dataclass(frozen=True, slots=True)
class ProgressPolicy:
    event_interval_seconds: float = 0.25
    checkpoint_interval_seconds: float = 5.0

    def __post_init__(self) -> None:
        if self.event_interval_seconds <= 0:
            raise ValueError("Progress event interval must be positive")
        if self.checkpoint_interval_seconds < self.event_interval_seconds:
            raise ValueError("Checkpoint interval cannot be shorter than event interval")


_DEFAULT_PROGRESS_POLICY = ProgressPolicy()


class CancellationSignal:
    """Thread-safe cancellation source implementing the read-only token port."""

    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()


class DownloadManager:
    """The only C5 service allowed to transition executing download tasks."""

    def __init__(
        self,
        *,
        downloader: Downloader,
        repository: TaskRepository,
        events: EventPublisher,
        clock: Clock,
        progress_policy: ProgressPolicy = _DEFAULT_PROGRESS_POLICY,
    ) -> None:
        self._downloader = downloader
        self._repository = repository
        self._events = events
        self._clock = clock
        self._progress_policy = progress_policy
        self._lock = RLock()
        self._signals: dict[TaskId, CancellationSignal] = {}
        self._last_checkpoints: dict[TaskId, UtcTimestamp] = {}

    def execute(self, task_id: TaskId) -> DownloadArtifact | None:
        signal = CancellationSignal()
        with self._lock:
            current = self._repository.get(task_id)
            if current is None or current.state is not TaskState.QUEUED:
                return None
            started_at = self._clock.now()
            downloading = current.transition(TaskState.DOWNLOADING, at=started_at)
            self._repository.replace(expected=current, updated=downloading)
            self._signals[task_id] = signal
            self._last_checkpoints[task_id] = started_at
        self._publish_state(current, downloading, started_at)

        relay = _ThrottledProgress(
            task_id=task_id,
            attempt_id=downloading.current_attempt.attempt_id,
            manager=self,
            interval_seconds=self._progress_policy.event_interval_seconds,
        )
        job = DownloadJob(
            task_id=task_id,
            attempt_id=downloading.current_attempt.attempt_id,
            request=downloading.request,
        )
        try:
            try:
                outcome = self._downloader.download(job, progress=relay, cancellation=signal)
            except Exception:
                _LOGGER.warning("application.failed")
                outcome = DownloadOutcome.failed(
                    Failure(
                        FailureCategory.UNEXPECTED,
                        "download.worker_unexpected",
                        retryable=False,
                    )
                )
            finally:
                try:
                    relay.flush()
                except Exception:
                    _LOGGER.warning("application.failed")

            if not isinstance(outcome, DownloadOutcome):
                outcome = DownloadOutcome.failed(
                    Failure(
                        FailureCategory.UNEXPECTED,
                        "download.invalid_outcome",
                        retryable=False,
                    )
                )
            settled = self._settle_download(
                task_id,
                job.attempt_id,
                cancellation=signal,
                failure=outcome.failure,
            )
            if (
                settled is None
                or settled.state is not TaskState.PROCESSING
                or outcome.artifact is None
            ):
                return None
            return outcome.artifact
        finally:
            with self._lock:
                self._signals.pop(task_id, None)
                self._last_checkpoints.pop(task_id, None)

    def cancel(self, task_id: TaskId) -> bool:
        """Cancel queued work immediately or request cooperative active cancellation."""

        with self._lock:
            signal = self._signals.get(task_id)
            if signal is not None:
                signal.cancel()
                return True
            current = self._repository.get(task_id)
            if current is None or current.state is not TaskState.QUEUED:
                return False
            occurred_at = self._clock.now()
            updated = current.transition(TaskState.CANCELLED, at=occurred_at)
            self._repository.replace(expected=current, updated=updated)
            event = _state_event(current, updated, occurred_at)
        self._publish(event)
        return True

    def interrupt(self, task_id: TaskId) -> bool:
        """Persist an active download as recoverable, then request worker stop."""

        with self._lock:
            current = self._repository.get(task_id)
            if current is None or current.state is not TaskState.DOWNLOADING:
                return False
            signal = self._signals.get(task_id)
            if signal is not None:
                signal.cancel()
            occurred_at = self._clock.now()
            updated = current.transition(TaskState.INTERRUPTED, at=occurred_at)
            self._repository.replace(expected=current, updated=updated)
        self._publish_state(current, updated, occurred_at)
        return True

    def _accept_progress(
        self, task_id: TaskId, attempt_id: AttemptId, progress: ProgressSnapshot
    ) -> None:
        with self._lock:
            current = self._repository.get(task_id)
            if (
                current is None
                or current.state is not TaskState.DOWNLOADING
                or current.current_attempt.attempt_id != attempt_id
            ):
                return
            validated = current.record_progress(progress)
            last_checkpoint = self._last_checkpoints.get(task_id)
            if last_checkpoint is None:
                return
            elapsed = (progress.captured_at.value - last_checkpoint.value).total_seconds()
            if elapsed >= self._progress_policy.checkpoint_interval_seconds:
                self._repository.replace(expected=current, updated=validated)
                self._last_checkpoints[task_id] = progress.captured_at
        self._publish(
            TaskProgressChanged(
                task_id=task_id,
                attempt_id=attempt_id,
                progress=progress,
                occurred_at=progress.captured_at,
            )
        )

    def _settle_download(
        self,
        task_id: TaskId,
        attempt_id: AttemptId,
        *,
        cancellation: CancellationSignal,
        failure: Failure | None = None,
    ) -> DownloadTask | None:
        with self._lock:
            current = self._repository.get(task_id)
            if (
                current is None
                or current.state is not TaskState.DOWNLOADING
                or current.current_attempt.attempt_id != attempt_id
            ):
                return None
            occurred_at = self._clock.now()
            if cancellation.is_cancelled() or (
                failure is not None and failure.category is FailureCategory.CANCELLED
            ):
                target = TaskState.CANCELLED
                persisted_failure = None
            elif failure is not None:
                target = TaskState.FAILED
                persisted_failure = failure
            else:
                target = TaskState.PROCESSING
                persisted_failure = None
            updated = current.transition(target, at=occurred_at, failure=persisted_failure)
            self._repository.replace(expected=current, updated=updated)
        self._publish_state(current, updated, occurred_at)
        if persisted_failure is not None:
            self._publish(
                TaskFailed(
                    task_id=task_id,
                    attempt_id=attempt_id,
                    failure=persisted_failure,
                    occurred_at=occurred_at,
                )
            )
        return updated

    def _publish_state(
        self, previous: DownloadTask, updated: DownloadTask, occurred_at: UtcTimestamp
    ) -> None:
        self._publish(_state_event(previous, updated, occurred_at))

    def _publish(self, event: ApplicationEvent) -> None:
        try:
            self._events.publish(event)
        except Exception:
            # Subscriber failures must not corrupt state or occupy a queue slot.
            _LOGGER.warning("application.failed")


class _ThrottledProgress(ProgressSink):
    def __init__(
        self,
        *,
        task_id: TaskId,
        attempt_id: AttemptId,
        manager: DownloadManager,
        interval_seconds: float,
    ) -> None:
        self._task_id = task_id
        self._attempt_id = attempt_id
        self._manager = manager
        self._interval_seconds = interval_seconds
        self._last_emitted: UtcTimestamp | None = None
        self._pending: ProgressSnapshot | None = None

    def report(self, progress: ProgressSnapshot) -> None:
        if self._last_emitted is not None:
            elapsed = (progress.captured_at.value - self._last_emitted.value).total_seconds()
            if elapsed < 0:
                return
            if elapsed < self._interval_seconds and progress.fraction != 1.0:
                self._pending = progress
                return
        self._emit(progress)

    def flush(self) -> None:
        if self._pending is not None:
            self._emit(self._pending)

    def _emit(self, progress: ProgressSnapshot) -> None:
        self._pending = None
        self._last_emitted = progress.captured_at
        self._manager._accept_progress(self._task_id, self._attempt_id, progress)


def _state_event(
    previous: DownloadTask, updated: DownloadTask, occurred_at: UtcTimestamp
) -> TaskStateChanged:
    return TaskStateChanged(
        task_id=updated.task_id,
        attempt_id=updated.current_attempt.attempt_id,
        previous_state=previous.state,
        state=updated.state,
        occurred_at=occurred_at,
    )
