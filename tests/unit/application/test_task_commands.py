from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from mediaflow.application import (
    CancelDownload,
    GetDownloads,
    GetHistory,
    PrepareResume,
    ResumeMode,
    RetryDownload,
    TaskNotFound,
    TaskQueued,
    TaskStateChanged,
)
from mediaflow.domain import (
    AttemptId,
    DownloadRequest,
    DownloadTask,
    Failure,
    FailureCategory,
    OutputPath,
    SourceUrl,
    TaskId,
    TaskState,
    UtcTimestamp,
    VideoPreset,
)
from tests.unit.application.fakes import (
    CollectingEventPublisher,
    FakeClock,
    FakeRecoveryStore,
    InMemoryTaskRepository,
)


def at(seconds: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 9, 6, tzinfo=UTC) + timedelta(seconds=seconds))


def task(tmp_path: Path, number: int = 1) -> DownloadTask:
    return DownloadTask.create(
        task_id=TaskId(UUID(int=100 + number)),
        attempt_id=AttemptId(UUID(int=number)),
        request=DownloadRequest(
            source_url=SourceUrl(f"https://example.com/{number}"),
            media_title=f"Media {number}",
            preset=VideoPreset(),
            output_directory=OutputPath(tmp_path),
        ),
        created_at=at(number),
    )


def test_cancel_commits_before_state_event(tmp_path: Path) -> None:
    operation_log: list[str] = []
    original = task(tmp_path)
    repository = InMemoryTaskRepository({original.task_id: original}, operation_log)
    events = CollectingEventPublisher(operation_log=operation_log)

    cancelled = CancelDownload(repository, events, FakeClock([at(2)])).execute(original.task_id)
    assert cancelled.state is TaskState.CANCELLED
    assert operation_log == ["repository.replace", "event.publish"]
    event = events.events[0]
    assert isinstance(event, TaskStateChanged)
    assert (event.previous_state, event.state) == (TaskState.QUEUED, TaskState.CANCELLED)


def test_committed_state_survives_event_delivery_failure(tmp_path: Path) -> None:
    original = task(tmp_path)
    repository = InMemoryTaskRepository({original.task_id: original})
    events = CollectingEventPublisher(fail=True)

    with pytest.raises(RuntimeError, match="event delivery"):
        CancelDownload(repository, events, FakeClock([at(2)])).execute(original.task_id)

    stored = repository.get(original.task_id)
    assert stored is not None
    assert stored.state is TaskState.CANCELLED


def test_retry_creates_new_attempt_and_emits_queued(tmp_path: Path) -> None:
    original = task(tmp_path).transition(
        TaskState.FAILED,
        at=at(2),
        failure=Failure(FailureCategory.NETWORK, "network.timeout", retryable=True),
    )
    repository = InMemoryTaskRepository({original.task_id: original})
    events = CollectingEventPublisher()

    retried = RetryDownload(repository, events, FakeClock([at(3)])).execute(original.task_id)
    assert len(retried.attempts) == 2
    assert retried.state is TaskState.QUEUED
    assert isinstance(events.events[0], TaskQueued)
    assert events.events[0].attempt_id == retried.current_attempt.attempt_id


def test_resume_requeues_same_attempt_only_with_real_partial(tmp_path: Path) -> None:
    original = task(tmp_path).transition(TaskState.DOWNLOADING, at=at(2))
    original = original.transition(TaskState.INTERRUPTED, at=at(3))
    repository = InMemoryTaskRepository({original.task_id: original})
    events = CollectingEventPublisher()

    plan = PrepareResume(
        repository, FakeRecoveryStore(partial=True), events, FakeClock([at(4)])
    ).execute(original.task_id)
    assert plan.task.state is TaskState.QUEUED
    assert plan.mode is ResumeMode.DOWNLOAD
    assert plan.task.current_attempt.attempt_id == original.current_attempt.attempt_id
    assert [type(event) for event in events.events] == [TaskStateChanged, TaskQueued]


def test_queries_delegate_download_and_history_projections(tmp_path: Path) -> None:
    active = task(tmp_path, 1)
    terminal = task(tmp_path, 2).transition(TaskState.CANCELLED, at=at(3))
    repository = InMemoryTaskRepository({active.task_id: active, terminal.task_id: terminal})
    assert GetDownloads(repository).execute() == (terminal, active)
    assert GetHistory(repository).execute() == (terminal,)


def test_command_reports_missing_task(tmp_path: Path) -> None:
    repository = InMemoryTaskRepository()
    with pytest.raises(TaskNotFound):
        CancelDownload(repository, CollectingEventPublisher(), FakeClock([at(1)])).execute(
            task(tmp_path).task_id
        )
