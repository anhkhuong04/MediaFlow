"""Application-owned processing lifecycle and processing-only retry."""

import logging
from threading import RLock

from mediaflow.application.download_manager import CancellationSignal
from mediaflow.application.events import (
    ApplicationEvent,
    OutputReady,
    TaskFailed,
    TaskProgressChanged,
    TaskStateChanged,
)
from mediaflow.application.models import (
    ConflictPolicy,
    DownloadArtifact,
    ProcessingJob,
    ProcessingOutcome,
)
from mediaflow.application.ports import (
    Clock,
    EventPublisher,
    MediaProcessor,
    ProgressSink,
    TaskRepository,
)
from mediaflow.domain import (
    AttemptId,
    DownloadTask,
    Failure,
    FailureCategory,
    OutputPath,
    ProgressSnapshot,
    ProgressStage,
    TaskId,
    TaskState,
)

_LOGGER = logging.getLogger("mediaflow.processing")


class ProcessingManager:
    """Own PROCESSING transitions and publish only verified final outputs."""

    def __init__(
        self,
        *,
        processor: MediaProcessor,
        repository: TaskRepository,
        events: EventPublisher,
        clock: Clock,
    ) -> None:
        self._processor = processor
        self._repository = repository
        self._events = events
        self._clock = clock
        self._lock = RLock()
        self._signals: dict[TaskId, CancellationSignal] = {}

    def execute(
        self,
        task_id: TaskId,
        artifact: DownloadArtifact,
        *,
        conflict_policy: ConflictPolicy = ConflictPolicy.RENAME,
    ) -> OutputPath | None:
        with self._lock:
            current = self._repository.get(task_id)
            if current is None or current.state is not TaskState.PROCESSING:
                return None
            signal = CancellationSignal()
            self._signals[task_id] = signal
            job = ProcessingJob(
                task_id=task_id,
                attempt_id=current.current_attempt.attempt_id,
                request=current.request,
                artifact=artifact,
                conflict_policy=conflict_policy,
            )
        return self._run(current, job, signal)

    def retry(
        self,
        task_id: TaskId,
        artifact: DownloadArtifact,
        *,
        conflict_policy: ConflictPolicy = ConflictPolicy.RENAME,
    ) -> OutputPath | None:
        """Create a PROCESSING attempt directly; the downloader is never invoked."""

        with self._lock:
            current = self._repository.get(task_id)
            if current is None:
                return None
            occurred_at = self._clock.now()
            updated = current.retry_processing(attempt_id=AttemptId.new(), at=occurred_at)
            self._repository.replace(expected=current, updated=updated)
            signal = CancellationSignal()
            self._signals[task_id] = signal
            job = ProcessingJob(
                task_id=task_id,
                attempt_id=updated.current_attempt.attempt_id,
                request=updated.request,
                artifact=artifact,
                conflict_policy=conflict_policy,
            )
        self._publish(
            TaskStateChanged(
                task_id=task_id,
                attempt_id=job.attempt_id,
                previous_state=current.state,
                state=TaskState.PROCESSING,
                occurred_at=occurred_at,
            )
        )
        return self._run(updated, job, signal)

    def cancel(self, task_id: TaskId) -> bool:
        with self._lock:
            signal = self._signals.get(task_id)
            if signal is not None:
                signal.cancel()
                return True
            current = self._repository.get(task_id)
            if current is None or current.state is not TaskState.PROCESSING:
                return False
            occurred_at = self._clock.now()
            updated = current.transition(TaskState.CANCELLED, at=occurred_at)
            self._repository.replace(expected=current, updated=updated)
        self._publish(
            TaskStateChanged(
                task_id=task_id,
                attempt_id=updated.current_attempt.attempt_id,
                previous_state=current.state,
                state=TaskState.CANCELLED,
                occurred_at=occurred_at,
            )
        )
        return True

    def interrupt(self, task_id: TaskId) -> bool:
        """Persist processing as recoverable before asking its worker to stop."""

        with self._lock:
            current = self._repository.get(task_id)
            if current is None or current.state is not TaskState.PROCESSING:
                return False
            signal = self._signals.get(task_id)
            if signal is not None:
                signal.cancel()
            occurred_at = self._clock.now()
            updated = current.transition(TaskState.INTERRUPTED, at=occurred_at)
            self._repository.replace(expected=current, updated=updated)
        self._publish(
            TaskStateChanged(
                task_id=task_id,
                attempt_id=updated.current_attempt.attempt_id,
                previous_state=TaskState.PROCESSING,
                state=TaskState.INTERRUPTED,
                occurred_at=occurred_at,
            )
        )
        return True

    def _run(
        self,
        started: DownloadTask,
        job: ProcessingJob,
        signal: CancellationSignal,
    ) -> OutputPath | None:
        progress = _ProcessingProgress(job=job, manager=self)
        try:
            try:
                outcome = self._processor.process(job, progress=progress, cancellation=signal)
            except Exception:
                _LOGGER.warning("application.failed")
                outcome = ProcessingOutcome.failed(
                    Failure(
                        FailureCategory.PROCESSING,
                        "processing.worker_unexpected",
                        retryable=True,
                    )
                )
            if not isinstance(outcome, ProcessingOutcome):
                outcome = ProcessingOutcome.failed(
                    Failure(
                        FailureCategory.PROCESSING,
                        "processing.invalid_outcome",
                        retryable=True,
                    )
                )
            return self._settle(started, job, signal, outcome)
        finally:
            with self._lock:
                self._signals.pop(job.task_id, None)

    def _settle(
        self,
        started: DownloadTask,
        job: ProcessingJob,
        cancellation: CancellationSignal,
        outcome: ProcessingOutcome,
    ) -> OutputPath | None:
        with self._lock:
            current = self._repository.get(job.task_id)
            if (
                current is None
                or current.state is not TaskState.PROCESSING
                or current.current_attempt.attempt_id != job.attempt_id
            ):
                return None
            occurred_at = self._clock.now()
            if outcome.output_path is not None:
                # Publication is already atomic and verified. A late cancel cannot
                # truthfully turn an available final file into a cancelled task.
                target = TaskState.COMPLETED
                failure = None
                output_path = outcome.output_path
            elif cancellation.is_cancelled() or (
                outcome.failure is not None
                and outcome.failure.category is FailureCategory.CANCELLED
            ):
                target = TaskState.CANCELLED
                failure = None
                output_path = None
            else:
                target = TaskState.FAILED
                failure = outcome.failure or Failure(
                    FailureCategory.PROCESSING,
                    "processing.invalid_outcome",
                    retryable=True,
                )
                output_path = None
            updated = current.transition(
                target,
                at=occurred_at,
                failure=failure,
                output_path=output_path,
            )
            self._repository.replace(expected=current, updated=updated)
        self._publish(
            TaskStateChanged(
                task_id=job.task_id,
                attempt_id=job.attempt_id,
                previous_state=started.state,
                state=target,
                occurred_at=occurred_at,
            )
        )
        if output_path is not None:
            self._publish(OutputReady(job.task_id, job.attempt_id, output_path, occurred_at))
        elif failure is not None:
            self._publish(TaskFailed(job.task_id, job.attempt_id, failure, occurred_at))
        return output_path

    def _accept_progress(self, job: ProcessingJob, progress: ProgressSnapshot) -> None:
        if progress.stage is not ProgressStage.PROCESSING:
            return
        with self._lock:
            current = self._repository.get(job.task_id)
            if (
                current is None
                or current.state is not TaskState.PROCESSING
                or current.current_attempt.attempt_id != job.attempt_id
            ):
                return
            current.record_progress(progress)
        self._publish(
            TaskProgressChanged(
                task_id=job.task_id,
                attempt_id=job.attempt_id,
                progress=progress,
                occurred_at=progress.captured_at,
            )
        )

    def _publish(self, event: ApplicationEvent) -> None:
        try:
            self._events.publish(event)
        except Exception:
            _LOGGER.warning("application.failed")


class _ProcessingProgress(ProgressSink):
    def __init__(self, *, job: ProcessingJob, manager: ProcessingManager) -> None:
        self._job = job
        self._manager = manager

    def report(self, progress: ProgressSnapshot) -> None:
        self._manager._accept_progress(self._job, progress)
