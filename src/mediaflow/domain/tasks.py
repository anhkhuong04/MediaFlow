"""Immutable download task aggregate and lifecycle rules."""

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final

from mediaflow.domain.errors import Failure
from mediaflow.domain.identifiers import AttemptId, OutputPath, SourceUrl, TaskId, UtcTimestamp
from mediaflow.domain.media import DownloadPreset
from mediaflow.domain.progress import ProgressSnapshot, ProgressStage


class TaskState(StrEnum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    PAUSED = "paused"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATES: Final = frozenset({TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED})

_ALLOWED_TRANSITIONS: Final[dict[TaskState, frozenset[TaskState]]] = {
    TaskState.QUEUED: frozenset({TaskState.DOWNLOADING, TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.DOWNLOADING: frozenset(
        {
            TaskState.PROCESSING,
            TaskState.PAUSED,
            TaskState.INTERRUPTED,
            TaskState.COMPLETED,
            TaskState.FAILED,
            TaskState.CANCELLED,
        }
    ),
    TaskState.PROCESSING: frozenset(
        {
            TaskState.INTERRUPTED,
            TaskState.COMPLETED,
            TaskState.FAILED,
            TaskState.CANCELLED,
        }
    ),
    TaskState.PAUSED: frozenset({TaskState.QUEUED, TaskState.INTERRUPTED, TaskState.CANCELLED}),
    TaskState.INTERRUPTED: frozenset({TaskState.QUEUED, TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.COMPLETED: frozenset(),
    TaskState.FAILED: frozenset(),
    TaskState.CANCELLED: frozenset(),
}


class InvalidTaskTransition(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DownloadRequest:
    source_url: SourceUrl
    media_title: str
    preset: DownloadPreset
    output_directory: OutputPath

    def __post_init__(self) -> None:
        if not self.media_title or not self.media_title.strip():
            raise ValueError("Download request title must be non-empty")


@dataclass(frozen=True, slots=True)
class DownloadAttempt:
    attempt_id: AttemptId
    number: int
    state: TaskState
    created_at: UtcTimestamp
    updated_at: UtcTimestamp
    finished_at: UtcTimestamp | None = None
    progress: ProgressSnapshot | None = None
    failure: Failure | None = None
    output_path: OutputPath | None = None

    def __post_init__(self) -> None:
        if self.number < 1:
            raise ValueError("Attempt number must be positive")
        _require_not_before(self.updated_at, self.created_at)
        if self.finished_at is not None:
            _require_not_before(self.finished_at, self.updated_at)
        if (self.state in TERMINAL_STATES) != (self.finished_at is not None):
            raise ValueError("Only terminal attempts must have a finished timestamp")
        if (self.state is TaskState.FAILED) != (self.failure is not None):
            raise ValueError("Only failed attempts must contain a failure")
        if (self.state is TaskState.COMPLETED) != (self.output_path is not None):
            raise ValueError("Only completed attempts must contain a final output path")


@dataclass(frozen=True, slots=True)
class DownloadTask:
    task_id: TaskId
    request: DownloadRequest
    created_at: UtcTimestamp
    attempts: tuple[DownloadAttempt, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempts", tuple(self.attempts))
        if not self.attempts:
            raise ValueError("Download task must contain at least one attempt")
        expected_numbers = tuple(range(1, len(self.attempts) + 1))
        if tuple(attempt.number for attempt in self.attempts) != expected_numbers:
            raise ValueError("Attempt numbers must be consecutive and start at one")
        if len({attempt.attempt_id for attempt in self.attempts}) != len(self.attempts):
            raise ValueError("Attempt IDs must be unique within a task")
        if any(attempt.created_at < self.created_at for attempt in self.attempts):
            raise ValueError("Attempt cannot predate its task")
        if any(attempt.state not in TERMINAL_STATES for attempt in self.attempts[:-1]):
            raise ValueError("Only the current attempt may be active")

    @classmethod
    def create(
        cls,
        *,
        task_id: TaskId,
        attempt_id: AttemptId,
        request: DownloadRequest,
        created_at: UtcTimestamp,
    ) -> "DownloadTask":
        attempt = DownloadAttempt(
            attempt_id=attempt_id,
            number=1,
            state=TaskState.QUEUED,
            created_at=created_at,
            updated_at=created_at,
        )
        return cls(task_id=task_id, request=request, created_at=created_at, attempts=(attempt,))

    @property
    def current_attempt(self) -> DownloadAttempt:
        return self.attempts[-1]

    @property
    def state(self) -> TaskState:
        return self.current_attempt.state

    def transition(
        self,
        target: TaskState,
        *,
        at: UtcTimestamp,
        failure: Failure | None = None,
        output_path: OutputPath | None = None,
    ) -> "DownloadTask":
        current = self.current_attempt
        if not is_transition_allowed(current.state, target):
            raise InvalidTaskTransition(f"Cannot transition from {current.state} to {target}")
        _require_not_before(at, current.updated_at)
        if target is TaskState.FAILED and failure is None:
            raise ValueError("A failed transition requires a failure")
        if target is not TaskState.FAILED and failure is not None:
            raise ValueError("Failure is only valid for a failed transition")
        if target is TaskState.COMPLETED and output_path is None:
            raise ValueError("A completed transition requires a verified output path")
        if target is not TaskState.COMPLETED and output_path is not None:
            raise ValueError("Output path is only valid for a completed transition")
        updated = replace(
            current,
            state=target,
            updated_at=at,
            finished_at=at if target in TERMINAL_STATES else None,
            failure=failure,
            output_path=output_path,
        )
        return self._replace_current(updated)

    def record_progress(self, progress: ProgressSnapshot) -> "DownloadTask":
        current = self.current_attempt
        expected_stage = {
            TaskState.DOWNLOADING: ProgressStage.DOWNLOADING,
            TaskState.PROCESSING: ProgressStage.PROCESSING,
        }.get(current.state)
        if expected_stage is None or progress.stage is not expected_stage:
            raise ValueError("Progress stage must match an active download or processing state")
        _require_not_before(progress.captured_at, current.updated_at)
        return self._replace_current(
            replace(current, updated_at=progress.captured_at, progress=progress)
        )

    def retry(self, *, attempt_id: AttemptId, at: UtcTimestamp) -> "DownloadTask":
        current = self.current_attempt
        if current.state not in {TaskState.FAILED, TaskState.CANCELLED}:
            raise InvalidTaskTransition("Only failed or cancelled tasks can start a retry attempt")
        if current.state is TaskState.FAILED and (
            current.failure is None or not current.failure.retryable
        ):
            raise InvalidTaskTransition("A non-retryable failure cannot start a retry attempt")
        _require_not_before(at, current.updated_at)
        if any(attempt.attempt_id == attempt_id for attempt in self.attempts):
            raise ValueError("Retry attempt ID must be unique")
        retry_attempt = DownloadAttempt(
            attempt_id=attempt_id,
            number=current.number + 1,
            state=TaskState.QUEUED,
            created_at=at,
            updated_at=at,
        )
        return replace(self, attempts=(*self.attempts, retry_attempt))

    def _replace_current(self, attempt: DownloadAttempt) -> "DownloadTask":
        return replace(self, attempts=(*self.attempts[:-1], attempt))


def is_transition_allowed(current: TaskState, target: TaskState) -> bool:
    return target in _ALLOWED_TRANSITIONS[current]


def allowed_transitions(state: TaskState) -> frozenset[TaskState]:
    return _ALLOWED_TRANSITIONS[state]


def _require_not_before(value: UtcTimestamp, lower_bound: UtcTimestamp) -> None:
    if value < lower_bound:
        raise ValueError("Timestamp cannot move backwards")
