from datetime import UTC, datetime, timedelta
from itertools import product
from pathlib import Path
from uuid import UUID

import pytest

from mediaflow.domain import (
    AttemptId,
    DownloadRequest,
    DownloadTask,
    Failure,
    FailureCategory,
    InvalidTaskTransition,
    OutputPath,
    ProgressSnapshot,
    SourceUrl,
    TaskId,
    TaskState,
    UtcTimestamp,
    VideoPreset,
    allowed_transitions,
    is_transition_allowed,
)

EXPECTED_TRANSITIONS = {
    TaskState.QUEUED: {TaskState.DOWNLOADING, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.DOWNLOADING: {
        TaskState.PROCESSING,
        TaskState.PAUSED,
        TaskState.INTERRUPTED,
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.CANCELLED,
    },
    TaskState.PROCESSING: {
        TaskState.INTERRUPTED,
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.CANCELLED,
    },
    TaskState.PAUSED: {TaskState.QUEUED, TaskState.INTERRUPTED, TaskState.CANCELLED},
    TaskState.INTERRUPTED: {TaskState.QUEUED, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.COMPLETED: set(),
    TaskState.FAILED: set(),
    TaskState.CANCELLED: set(),
}


def at(seconds: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 9, 6, tzinfo=UTC) + timedelta(seconds=seconds))


def attempt_id(number: int) -> AttemptId:
    return AttemptId(UUID(int=number))


def create_task(tmp_path: Path) -> DownloadTask:
    request = DownloadRequest(
        source_url=SourceUrl("https://example.com/media"),
        media_title="Example",
        preset=VideoPreset(),
        output_directory=OutputPath(tmp_path),
    )
    return DownloadTask.create(
        task_id=TaskId(UUID(int=100)),
        attempt_id=attempt_id(1),
        request=request,
        created_at=at(0),
    )


def task_in_state(state: TaskState, tmp_path: Path) -> DownloadTask:
    task = create_task(tmp_path)
    if state is TaskState.QUEUED:
        return task
    if state is TaskState.FAILED:
        return task.transition(
            state,
            at=at(1),
            failure=Failure(FailureCategory.DOWNLOAD, "download.failed", retryable=True),
        )
    if state is TaskState.CANCELLED:
        return task.transition(state, at=at(1))
    task = task.transition(TaskState.DOWNLOADING, at=at(1))
    if state is TaskState.DOWNLOADING:
        return task
    if state in {TaskState.PAUSED, TaskState.INTERRUPTED}:
        return task.transition(state, at=at(2))
    if state is TaskState.COMPLETED:
        return task.transition(state, at=at(2), output_path=OutputPath(tmp_path / "out.mp4"))
    return task.transition(TaskState.PROCESSING, at=at(2))


def transition_to(task: DownloadTask, target: TaskState, tmp_path: Path) -> DownloadTask:
    if target is TaskState.FAILED:
        return task.transition(
            target,
            at=at(10),
            failure=Failure(FailureCategory.DOWNLOAD, "download.failed", retryable=True),
        )
    if target is TaskState.COMPLETED:
        return task.transition(target, at=at(10), output_path=OutputPath(tmp_path / "output.mp4"))
    return task.transition(target, at=at(10))


@pytest.mark.parametrize(("current", "target"), list(product(TaskState, repeat=2)))
def test_complete_transition_matrix_and_aggregate_guard(
    current: TaskState, target: TaskState, tmp_path: Path
) -> None:
    expected = target in EXPECTED_TRANSITIONS[current]
    assert is_transition_allowed(current, target) is expected
    assert allowed_transitions(current) == frozenset(EXPECTED_TRANSITIONS[current])
    task = task_in_state(current, tmp_path)
    if expected:
        assert transition_to(task, target, tmp_path).state is target
    else:
        with pytest.raises(InvalidTaskTransition):
            transition_to(task, target, tmp_path)


def test_download_at_one_hundred_percent_can_still_be_processing(tmp_path: Path) -> None:
    task = create_task(tmp_path).transition(TaskState.DOWNLOADING, at=at(1))
    task = task.record_progress(
        ProgressSnapshot.downloading(
            captured_at=at(2), downloaded_bytes=100, total_bytes=100, eta_seconds=0
        )
    )
    assert task.state is TaskState.DOWNLOADING
    assert task.current_attempt.progress is not None
    assert task.current_attempt.progress.fraction == 1.0
    task = task.transition(TaskState.PROCESSING, at=at(3))
    assert task.state is TaskState.PROCESSING
    task = task.record_progress(ProgressSnapshot.processing(captured_at=at(4)))
    task = task.transition(
        TaskState.COMPLETED, at=at(5), output_path=OutputPath(tmp_path / "output.mp4")
    )
    assert task.state is TaskState.COMPLETED


def test_retry_preserves_request_and_keeps_terminal_attempt(tmp_path: Path) -> None:
    task = create_task(tmp_path)
    failed = task.transition(
        TaskState.FAILED,
        at=at(1),
        failure=Failure(FailureCategory.NETWORK, "network.timeout", retryable=True),
    )
    retried = failed.retry(attempt_id=attempt_id(2), at=at(2))
    assert retried.request is failed.request
    assert retried.state is TaskState.QUEUED
    assert retried.current_attempt.number == 2
    assert retried.current_attempt.failure is None
    assert retried.attempts[0].state is TaskState.FAILED
    assert retried.attempts[0].finished_at == at(1)


def test_retry_requires_terminal_retryable_task_and_unique_id(tmp_path: Path) -> None:
    task = create_task(tmp_path)
    with pytest.raises(InvalidTaskTransition):
        task.retry(attempt_id=attempt_id(2), at=at(1))
    failed = task.transition(
        TaskState.FAILED,
        at=at(1),
        failure=Failure(FailureCategory.DOWNLOAD, "download.failed", retryable=True),
    )
    with pytest.raises(ValueError):
        failed.retry(attempt_id=attempt_id(1), at=at(2))
    non_retryable = task.transition(
        TaskState.FAILED,
        at=at(1),
        failure=Failure(FailureCategory.ACCESS_DENIED, "access.denied", retryable=False),
    )
    with pytest.raises(InvalidTaskTransition):
        non_retryable.retry(attempt_id=attempt_id(2), at=at(2))


def test_processing_retry_starts_new_processing_attempt_and_preserves_request(
    tmp_path: Path,
) -> None:
    processing = (
        create_task(tmp_path)
        .transition(TaskState.DOWNLOADING, at=at(1))
        .transition(TaskState.PROCESSING, at=at(2))
    )
    failed = processing.transition(
        TaskState.FAILED,
        at=at(3),
        failure=Failure(
            FailureCategory.PROCESSING,
            "processing.ffmpeg_failed",
            retryable=True,
        ),
    )

    retried = failed.retry_processing(attempt_id=attempt_id(2), at=at(4))

    assert retried.request is failed.request
    assert retried.state is TaskState.PROCESSING
    assert retried.current_attempt.number == 2
    assert retried.attempts[0] == failed.current_attempt
    with pytest.raises(InvalidTaskTransition):
        failed.retry(attempt_id=attempt_id(3), at=at(4))


def test_processing_retry_rejects_nonprocessing_or_nonretryable_failure(
    tmp_path: Path,
) -> None:
    download_failure = create_task(tmp_path).transition(
        TaskState.FAILED,
        at=at(1),
        failure=Failure(FailureCategory.DOWNLOAD, "download.failed", retryable=True),
    )
    processing = (
        create_task(tmp_path)
        .transition(TaskState.DOWNLOADING, at=at(1))
        .transition(TaskState.PROCESSING, at=at(2))
    )
    nonretryable = processing.transition(
        TaskState.FAILED,
        at=at(3),
        failure=Failure(
            FailureCategory.PROCESSING,
            "processing.invalid_input",
            retryable=False,
        ),
    )

    with pytest.raises(InvalidTaskTransition):
        download_failure.retry_processing(attempt_id=attempt_id(2), at=at(2))
    with pytest.raises(InvalidTaskTransition):
        nonretryable.retry_processing(attempt_id=attempt_id(2), at=at(4))


def test_transition_requires_failure_or_verified_output_as_appropriate(tmp_path: Path) -> None:
    queued = create_task(tmp_path)
    with pytest.raises(ValueError):
        queued.transition(TaskState.FAILED, at=at(1))
    downloading = queued.transition(TaskState.DOWNLOADING, at=at(1))
    with pytest.raises(ValueError):
        downloading.transition(TaskState.COMPLETED, at=at(2))


def test_progress_must_match_state_and_move_forward_in_time(tmp_path: Path) -> None:
    queued = create_task(tmp_path)
    progress = ProgressSnapshot.downloading(captured_at=at(1), downloaded_bytes=1)
    with pytest.raises(ValueError):
        queued.record_progress(progress)
    downloading = queued.transition(TaskState.DOWNLOADING, at=at(2))
    with pytest.raises(ValueError):
        downloading.record_progress(progress)
    with pytest.raises(ValueError):
        downloading.record_progress(ProgressSnapshot.processing(captured_at=at(3)))
