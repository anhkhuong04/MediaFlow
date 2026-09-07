"""Application workflows and the authoritative transaction ordering.

Every durable task mutation is committed through ``TaskRepository`` before its
event is published. Publisher failures propagate after the commit; callers must
refresh authoritative state and must not repeat the command blindly.
"""

from dataclasses import dataclass

from mediaflow.application.events import (
    AnalysisFailed,
    AnalysisSucceeded,
    TaskQueued,
    TaskStateChanged,
)
from mediaflow.application.format_availability import require_preset_available
from mediaflow.application.ports import (
    Analyzer,
    CancellationToken,
    Clock,
    EventPublisher,
    TaskRepository,
)
from mediaflow.domain import (
    AnalysisOperation,
    AttemptId,
    DownloadPreset,
    DownloadRequest,
    DownloadTask,
    Failure,
    FailureCategory,
    MediaInfo,
    OutputPath,
    SourceUrl,
    TaskId,
    TaskState,
    UtcTimestamp,
)


class TaskNotFound(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class AnalyzeUrl:
    analyzer: Analyzer
    events: EventPublisher
    clock: Clock

    def execute(
        self, source_url: SourceUrl, *, cancellation: CancellationToken
    ) -> AnalysisOperation:
        operation = AnalysisOperation.start(source_url=source_url, at=self.clock.now())
        if cancellation.is_cancelled():
            return self._cancel(operation)

        outcome = self.analyzer.analyze(source_url, cancellation=cancellation)
        if cancellation.is_cancelled():
            return self._cancel(operation)

        occurred_at = self.clock.now()
        if outcome.media is not None:
            completed = operation.succeed(media=outcome.media, at=occurred_at)
            self.events.publish(
                AnalysisSucceeded(
                    source_url=source_url, media=outcome.media, occurred_at=occurred_at
                )
            )
            return completed

        if outcome.failure is None:
            raise AssertionError("Analysis outcome invariant was violated")
        if outcome.failure.category is FailureCategory.CANCELLED:
            return self._cancel(operation, at=occurred_at)
        failed = operation.fail(failure=outcome.failure, at=occurred_at)
        self.events.publish(
            AnalysisFailed(source_url=source_url, failure=outcome.failure, occurred_at=occurred_at)
        )
        return failed

    def _cancel(
        self, operation: AnalysisOperation, *, at: UtcTimestamp | None = None
    ) -> AnalysisOperation:
        occurred_at = at or self.clock.now()
        cancelled = operation.cancel(at=occurred_at)
        self.events.publish(
            AnalysisFailed(
                source_url=operation.source_url,
                failure=Failure(FailureCategory.CANCELLED, "analysis.cancelled", retryable=False),
                occurred_at=occurred_at,
            )
        )
        return cancelled


@dataclass(frozen=True, slots=True)
class EnqueueDownload:
    repository: TaskRepository
    events: EventPublisher
    clock: Clock

    def execute(
        self, *, media: MediaInfo, preset: DownloadPreset, output_directory: OutputPath
    ) -> DownloadTask:
        require_preset_available(media, preset)
        created_at = self.clock.now()
        request = DownloadRequest(
            source_url=media.source_url,
            media_title=media.title,
            preset=preset,
            output_directory=output_directory,
        )
        task = DownloadTask.create(
            task_id=TaskId.new(),
            attempt_id=AttemptId.new(),
            request=request,
            created_at=created_at,
        )
        self.repository.add(task)
        self.events.publish(
            TaskQueued(
                task_id=task.task_id,
                attempt_id=task.current_attempt.attempt_id,
                request=task.request,
                occurred_at=created_at,
            )
        )
        return task


@dataclass(frozen=True, slots=True)
class CancelDownload:
    repository: TaskRepository
    events: EventPublisher
    clock: Clock

    def execute(self, task_id: TaskId) -> DownloadTask:
        current = _require_task(self.repository, task_id)
        occurred_at = self.clock.now()
        updated = current.transition(TaskState.CANCELLED, at=occurred_at)
        self.repository.replace(expected=current, updated=updated)
        self.events.publish(_state_event(current, updated, occurred_at))
        return updated


@dataclass(frozen=True, slots=True)
class RetryDownload:
    repository: TaskRepository
    events: EventPublisher
    clock: Clock

    def execute(self, task_id: TaskId) -> DownloadTask:
        current = _require_task(self.repository, task_id)
        occurred_at = self.clock.now()
        updated = current.retry(attempt_id=AttemptId.new(), at=occurred_at)
        self.repository.replace(expected=current, updated=updated)
        self.events.publish(
            TaskQueued(
                task_id=updated.task_id,
                attempt_id=updated.current_attempt.attempt_id,
                request=updated.request,
                occurred_at=occurred_at,
            )
        )
        return updated


@dataclass(frozen=True, slots=True)
class GetDownloads:
    repository: TaskRepository

    def execute(self) -> tuple[DownloadTask, ...]:
        return self.repository.list_downloads()


@dataclass(frozen=True, slots=True)
class GetHistory:
    repository: TaskRepository

    def execute(self) -> tuple[DownloadTask, ...]:
        return self.repository.list_history()


def _require_task(repository: TaskRepository, task_id: TaskId) -> DownloadTask:
    task = repository.get(task_id)
    if task is None:
        raise TaskNotFound(str(task_id))
    return task


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
