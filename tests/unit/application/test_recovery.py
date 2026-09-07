from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mediaflow.application import (
    DownloadArtifact,
    PrepareProcessingRetry,
    PrepareResume,
    RestartDownload,
    ResumeMode,
    ResumeUnavailable,
    StartupRecovery,
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


def test_startup_recovery_is_idempotent_and_preserves_interrupted_stage(tmp_path: Path) -> None:
    tasks = []
    for index, state in enumerate(
        (TaskState.DOWNLOADING, TaskState.PROCESSING, TaskState.PAUSED), start=1
    ):
        active = _task(tmp_path, index).transition(TaskState.DOWNLOADING, at=_at(10))
        if state is not TaskState.DOWNLOADING:
            active = active.transition(state, at=_at(11))
        tasks.append(active)
    repository = InMemoryTaskRepository({item.task_id: item for item in tasks})
    events = CollectingEventPublisher()
    recovery = StartupRecovery(
        repository,
        events,
        FakeClock([_at(20), _at(21), _at(22)]),
    )

    first = recovery.execute()
    second = recovery.execute()

    assert set(first.recovered_task_ids) == {item.task_id for item in tasks}
    assert second.recovered_task_ids == ()
    assert len(events.events) == 3
    assert {
        repository.get(item.task_id).current_attempt.interrupted_from  # type: ignore[union-attr]
        for item in tasks
    } == {TaskState.DOWNLOADING, TaskState.PROCESSING, TaskState.PAUSED}


def test_resume_refuses_to_pretend_when_partial_is_missing(tmp_path: Path) -> None:
    interrupted = (
        _task(tmp_path, 1)
        .transition(TaskState.DOWNLOADING, at=_at(1))
        .transition(TaskState.INTERRUPTED, at=_at(2))
    )
    repository = InMemoryTaskRepository({interrupted.task_id: interrupted})

    with pytest.raises(ResumeUnavailable, match="resume.partial_missing"):
        PrepareResume(
            repository,
            FakeRecoveryStore(partial=False),
            CollectingEventPublisher(),
            FakeClock([_at(3)]),
        ).execute(interrupted.task_id)

    assert repository.get(interrupted.task_id) == interrupted

    restarted = RestartDownload(
        repository, CollectingEventPublisher(), FakeClock([_at(4)])
    ).execute(interrupted.task_id)
    assert restarted.mode is ResumeMode.DOWNLOAD
    assert restarted.task.request == interrupted.request
    assert len(restarted.task.attempts) == 2
    assert restarted.task.attempts[0].failure is not None
    assert restarted.task.attempts[0].failure.code == "recovery.full_restart"
    assert restarted.task.state is TaskState.QUEUED


def test_processing_resume_and_retry_never_invoke_downloader_or_change_request(
    tmp_path: Path,
) -> None:
    artifact = DownloadArtifact((OutputPath(tmp_path / "input.webm"),), True)
    processing = (
        _task(tmp_path, 1)
        .transition(TaskState.DOWNLOADING, at=_at(1))
        .transition(TaskState.PROCESSING, at=_at(2))
    )
    interrupted = processing.transition(TaskState.INTERRUPTED, at=_at(3))
    repository = InMemoryTaskRepository({interrupted.task_id: interrupted})
    plan = PrepareResume(
        repository,
        FakeRecoveryStore(artifact=artifact),
        CollectingEventPublisher(),
        FakeClock([_at(4)]),
    ).execute(interrupted.task_id)
    assert plan.mode is ResumeMode.PROCESSING
    assert plan.artifact == artifact
    assert plan.task.request == interrupted.request
    assert len(plan.task.attempts) == 1

    failed = processing.transition(
        TaskState.FAILED,
        at=_at(3),
        failure=Failure(FailureCategory.PROCESSING, "processing.failed", True),
    )
    repository = InMemoryTaskRepository({failed.task_id: failed})
    retry = PrepareProcessingRetry(
        repository,
        FakeRecoveryStore(artifact=artifact),
        CollectingEventPublisher(),
        FakeClock([_at(4)]),
    ).execute(failed.task_id)
    assert retry.mode is ResumeMode.PROCESSING
    assert retry.task.request == failed.request
    assert retry.task.attempts[:-1] == failed.attempts
    assert retry.task.current_attempt.number == 2


def _task(tmp_path: Path, index: int) -> DownloadTask:
    return DownloadTask.create(
        task_id=TaskId.new(),
        attempt_id=AttemptId.new(),
        request=DownloadRequest(
            SourceUrl(f"https://example.com/{index}"),
            f"Media {index}",
            VideoPreset(),
            OutputPath(tmp_path),
        ),
        created_at=_at(0),
    )


def _at(seconds: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 9, 7, tzinfo=UTC) + timedelta(seconds=seconds))
