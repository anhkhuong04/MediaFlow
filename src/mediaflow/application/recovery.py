"""Startup reconciliation and truthful retry/resume preparation."""

from dataclasses import dataclass

from mediaflow.application.events import TaskQueued, TaskStateChanged
from mediaflow.application.models import ResumeMode, ResumePlan
from mediaflow.application.ports import Clock, EventPublisher, RecoveryStore, TaskRepository
from mediaflow.domain import AttemptId, TaskId, TaskState


class ResumeUnavailable(RuntimeError):
    """The requested operation cannot reuse verified local staging data."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    recovered_task_ids: tuple[TaskId, ...]


@dataclass(frozen=True, slots=True)
class StartupRecovery:
    repository: TaskRepository
    events: EventPublisher
    clock: Clock

    def execute(self) -> RecoveryReport:
        recovered: list[TaskId] = []
        for current in self.repository.list_downloads():
            if current.state not in {
                TaskState.DOWNLOADING,
                TaskState.PROCESSING,
                TaskState.PAUSED,
            }:
                continue
            occurred_at = self.clock.now()
            updated = current.transition(TaskState.INTERRUPTED, at=occurred_at)
            self.repository.replace(expected=current, updated=updated)
            self.events.publish(
                TaskStateChanged(
                    task_id=current.task_id,
                    attempt_id=current.current_attempt.attempt_id,
                    previous_state=current.state,
                    state=TaskState.INTERRUPTED,
                    occurred_at=occurred_at,
                )
            )
            recovered.append(current.task_id)
        return RecoveryReport(tuple(recovered))


@dataclass(frozen=True, slots=True)
class PrepareResume:
    repository: TaskRepository
    recovery_store: RecoveryStore
    events: EventPublisher
    clock: Clock

    def execute(self, task_id: TaskId) -> ResumePlan:
        current = self.repository.get(task_id)
        if current is None:
            raise LookupError(str(task_id))
        if current.state is not TaskState.INTERRUPTED:
            raise ResumeUnavailable("resume.invalid_state")

        source = current.current_attempt.interrupted_from
        occurred_at = self.clock.now()
        if source is TaskState.PROCESSING:
            artifact = self.recovery_store.load_processing_artifact(current)
            if artifact is None:
                raise ResumeUnavailable("resume.processing_inputs_missing")
            updated = current.transition(TaskState.PROCESSING, at=occurred_at)
            mode = ResumeMode.PROCESSING
        else:
            if not self.recovery_store.has_resumable_partial(current):
                raise ResumeUnavailable("resume.partial_missing")
            artifact = None
            updated = current.transition(TaskState.QUEUED, at=occurred_at)
            mode = ResumeMode.DOWNLOAD

        self.repository.replace(expected=current, updated=updated)
        self.events.publish(
            TaskStateChanged(
                task_id=task_id,
                attempt_id=updated.current_attempt.attempt_id,
                previous_state=TaskState.INTERRUPTED,
                state=updated.state,
                occurred_at=occurred_at,
            )
        )
        if mode is ResumeMode.DOWNLOAD:
            self.events.publish(
                TaskQueued(
                    task_id=task_id,
                    attempt_id=updated.current_attempt.attempt_id,
                    request=updated.request,
                    occurred_at=occurred_at,
                )
            )
        return ResumePlan(updated, mode, artifact)


@dataclass(frozen=True, slots=True)
class PrepareProcessingRetry:
    repository: TaskRepository
    recovery_store: RecoveryStore
    events: EventPublisher
    clock: Clock

    def execute(self, task_id: TaskId) -> ResumePlan:
        current = self.repository.get(task_id)
        if current is None:
            raise LookupError(str(task_id))
        artifact = self.recovery_store.load_processing_artifact(current)
        if artifact is None:
            raise ResumeUnavailable("retry.processing_inputs_missing")
        occurred_at = self.clock.now()
        updated = current.retry_processing(attempt_id=AttemptId.new(), at=occurred_at)
        self.repository.replace(expected=current, updated=updated)
        self.events.publish(
            TaskStateChanged(
                task_id=task_id,
                attempt_id=updated.current_attempt.attempt_id,
                previous_state=current.state,
                state=TaskState.PROCESSING,
                occurred_at=occurred_at,
            )
        )
        return ResumePlan(updated, ResumeMode.PROCESSING, artifact)


@dataclass(frozen=True, slots=True)
class RestartDownload:
    """Explicit full-download fallback when no resumable partial remains."""

    repository: TaskRepository
    events: EventPublisher
    clock: Clock

    def execute(self, task_id: TaskId) -> ResumePlan:
        current = self.repository.get(task_id)
        if current is None:
            raise LookupError(str(task_id))
        occurred_at = self.clock.now()
        updated = current.restart_download(attempt_id=AttemptId.new(), at=occurred_at)
        self.repository.replace(expected=current, updated=updated)
        self.events.publish(
            TaskQueued(
                task_id=task_id,
                attempt_id=updated.current_attempt.attempt_id,
                request=updated.request,
                occurred_at=occurred_at,
            )
        )
        return ResumePlan(updated, ResumeMode.DOWNLOAD)


# Preserve the C2 command name while making its stronger C7 dependencies explicit.
ResumeDownload = PrepareResume
