import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mediaflow.application import StartupRecovery, TaskRepository, TaskRepositoryConflict
from mediaflow.domain import (
    AttemptId,
    AudioContainer,
    AudioPreset,
    DownloadPreset,
    DownloadRequest,
    DownloadTask,
    Failure,
    FailureCategory,
    OutputPath,
    ProgressSnapshot,
    SourceUrl,
    TaskId,
    TaskState,
    UtcTimestamp,
    VideoContainer,
    VideoPreset,
    VideoQuality,
)
from mediaflow.infrastructure.persistence import SQLiteTaskRepository
from tests.unit.application.fakes import CollectingEventPublisher, FakeClock


def test_round_trip_preserves_request_attempt_history_failure_and_output(tmp_path: Path) -> None:
    repository: TaskRepository = SQLiteTaskRepository(tmp_path / "mediaflow.db")
    task = _task(tmp_path, preset=AudioPreset(container=AudioContainer.MP3))
    failed = task.transition(
        TaskState.FAILED,
        at=_at(1),
        failure=Failure(FailureCategory.NETWORK, "network.timeout", retryable=True),
    )
    retried = failed.retry(attempt_id=AttemptId.new(), at=_at(2))
    downloading = retried.transition(TaskState.DOWNLOADING, at=_at(3))
    completed = downloading.transition(
        TaskState.COMPLETED,
        at=_at(4),
        output_path=OutputPath((tmp_path / "final.mp3").resolve()),
    )

    repository.add(completed)
    reopened = SQLiteTaskRepository(tmp_path / "mediaflow.db")

    assert reopened.get(completed.task_id) == completed


def test_video_preset_fields_round_trip(tmp_path: Path) -> None:
    repository = SQLiteTaskRepository(tmp_path / "mediaflow.db")
    task = _task(
        tmp_path,
        preset=VideoPreset(
            quality=VideoQuality.P1080,
            container=VideoContainer.MKV,
            preferred_frames_per_second=60,
        ),
    )

    repository.add(task)

    assert repository.get(task.task_id) == task


def test_remove_deletes_one_task_and_cascades_dependent_records(tmp_path: Path) -> None:
    repository = SQLiteTaskRepository(tmp_path / "mediaflow.db")
    task = _task(tmp_path)
    repository.add(task)

    assert repository.remove(task.task_id)
    assert repository.get(task.task_id) is None
    assert not repository.remove(task.task_id)


def test_processing_only_retry_attempt_round_trips_without_schema_change(
    tmp_path: Path,
) -> None:
    repository = SQLiteTaskRepository(tmp_path / "mediaflow.db")
    processing = (
        _task(tmp_path)
        .transition(TaskState.DOWNLOADING, at=_at(1))
        .transition(TaskState.PROCESSING, at=_at(2))
    )
    failed = processing.transition(
        TaskState.FAILED,
        at=_at(3),
        failure=Failure(
            FailureCategory.PROCESSING,
            "processing.ffmpeg_failed",
            retryable=True,
        ),
    )
    retried = failed.retry_processing(attempt_id=AttemptId.new(), at=_at(4))

    repository.add(retried)

    assert SQLiteTaskRepository(tmp_path / "mediaflow.db").get(retried.task_id) == retried


def test_interrupted_origin_survives_database_reopen(tmp_path: Path) -> None:
    database_path = tmp_path / "mediaflow.db"
    repository = SQLiteTaskRepository(database_path)
    interrupted = (
        _task(tmp_path)
        .transition(TaskState.DOWNLOADING, at=_at(1))
        .transition(TaskState.INTERRUPTED, at=_at(2))
    )
    repository.add(interrupted)

    restored = SQLiteTaskRepository(database_path).get(interrupted.task_id)

    assert restored == interrupted
    assert restored is not None
    assert restored.current_attempt.interrupted_from is TaskState.DOWNLOADING


@pytest.mark.parametrize("stage", [TaskState.DOWNLOADING, TaskState.PROCESSING, TaskState.PAUSED])
def test_startup_recovery_survives_reopen_at_each_execution_stage(
    stage: TaskState, tmp_path: Path
) -> None:
    database_path = tmp_path / f"{stage.value}.db"
    repository = SQLiteTaskRepository(database_path)
    active = _task(tmp_path).transition(TaskState.DOWNLOADING, at=_at(1))
    if stage is not TaskState.DOWNLOADING:
        active = active.transition(stage, at=_at(2))
    repository.add(active)

    reopened = SQLiteTaskRepository(database_path)
    recovery = StartupRecovery(
        reopened,
        CollectingEventPublisher(),
        FakeClock([_at(3)]),
    )
    assert recovery.execute().recovered_task_ids == (active.task_id,)
    assert recovery.execute().recovered_task_ids == ()

    restored = SQLiteTaskRepository(database_path).get(active.task_id)
    assert restored is not None
    assert restored.state is TaskState.INTERRUPTED
    assert restored.current_attempt.interrupted_from is stage


def test_schema_persists_typed_source_but_has_no_auth_payload_columns(tmp_path: Path) -> None:
    database_path = tmp_path / "mediaflow.db"
    repository = SQLiteTaskRepository(database_path)
    task = _task(tmp_path)
    repository.add(task)

    with closing(sqlite3.connect(database_path)) as connection, connection:
        stored_url = connection.execute(
            "SELECT source_url FROM download_tasks WHERE task_id = ?", (str(task.task_id),)
        ).fetchone()
        columns = {
            row[1].lower()
            for table in ("download_tasks", "download_attempts", "task_outputs")
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }

    assert stored_url == (str(task.request.source_url),)
    assert not any(
        sensitive in column
        for column in columns
        for sensitive in ("cookie", "header", "authorization", "token", "password")
    )


def test_progress_telemetry_is_not_persisted_but_checkpoint_timestamp_is(tmp_path: Path) -> None:
    repository = SQLiteTaskRepository(tmp_path / "mediaflow.db")
    downloading = _task(tmp_path).transition(TaskState.DOWNLOADING, at=_at(1))
    with_progress = downloading.record_progress(
        ProgressSnapshot.downloading(
            captured_at=_at(2),
            downloaded_bytes=500,
            total_bytes=1000,
            speed_bytes_per_second=25.0,
            eta_seconds=20.0,
        )
    )

    repository.add(with_progress)
    restored = repository.get(with_progress.task_id)

    assert restored is not None
    assert restored.current_attempt.updated_at == _at(2)
    assert restored.current_attempt.progress is None
    with closing(sqlite3.connect(tmp_path / "mediaflow.db")) as connection, connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(download_attempts)").fetchall()
        }
    assert "speed_bytes_per_second" not in columns
    assert "eta_seconds" not in columns


def test_expected_in_memory_telemetry_does_not_create_false_replace_conflict(
    tmp_path: Path,
) -> None:
    repository = SQLiteTaskRepository(tmp_path / "mediaflow.db")
    downloading = _task(tmp_path).transition(TaskState.DOWNLOADING, at=_at(1))
    expected_with_telemetry = downloading.record_progress(
        ProgressSnapshot.downloading(
            captured_at=_at(2),
            downloaded_bytes=750,
            total_bytes=1000,
            speed_bytes_per_second=50.0,
            eta_seconds=5.0,
        )
    )
    repository.add(expected_with_telemetry)
    paused = expected_with_telemetry.transition(TaskState.PAUSED, at=_at(3))

    repository.replace(expected=expected_with_telemetry, updated=paused)

    restored = repository.get(paused.task_id)
    assert restored is not None
    assert restored.state is TaskState.PAUSED
    assert restored.current_attempt.progress is None


def test_replace_uses_durable_optimistic_comparison(tmp_path: Path) -> None:
    repository = SQLiteTaskRepository(tmp_path / "mediaflow.db")
    original = _task(tmp_path)
    repository.add(original)
    first_reader = repository.get(original.task_id)
    stale_reader = repository.get(original.task_id)
    assert first_reader is not None
    assert stale_reader is not None
    downloading = first_reader.transition(TaskState.DOWNLOADING, at=_at(1))
    repository.replace(expected=first_reader, updated=downloading)

    with pytest.raises(TaskRepositoryConflict):
        repository.replace(
            expected=stale_reader,
            updated=stale_reader.transition(TaskState.CANCELLED, at=_at(2)),
        )

    assert repository.get(original.task_id) == downloading


def test_history_contains_only_terminal_tasks_newest_first(tmp_path: Path) -> None:
    repository = SQLiteTaskRepository(tmp_path / "mediaflow.db")
    active = _task(tmp_path, created_at=_at(1))
    older = _task(tmp_path, created_at=_at(0)).transition(TaskState.CANCELLED, at=_at(2))
    newer = _task(tmp_path, created_at=_at(0)).transition(TaskState.CANCELLED, at=_at(3))
    repository.add(active)
    repository.add(older)
    repository.add(newer)

    assert repository.list_history() == (newer, older)
    assert set(repository.list_downloads()) == {active, older, newer}


def test_duplicate_task_is_a_repository_conflict_and_does_not_damage_existing_data(
    tmp_path: Path,
) -> None:
    repository = SQLiteTaskRepository(tmp_path / "mediaflow.db")
    task = _task(tmp_path)
    repository.add(task)

    with pytest.raises(TaskRepositoryConflict):
        repository.add(task)

    assert repository.get(task.task_id) == task


def test_repository_operations_release_database_file_handle(tmp_path: Path) -> None:
    """Windows must be able to move the database after all adapter calls return."""

    database_path = tmp_path / "mediaflow.db"
    moved_path = tmp_path / "moved.db"
    repository = SQLiteTaskRepository(database_path)
    task = _task(tmp_path)
    repository.add(task)
    assert repository.get(task.task_id) == task
    assert repository.list_downloads() == (task,)
    assert repository.list_history() == ()

    database_path.replace(moved_path)

    assert moved_path.is_file()
    assert not database_path.exists()


def test_failed_multi_table_insert_rolls_back(tmp_path: Path) -> None:
    repository = SQLiteTaskRepository(tmp_path / "mediaflow.db")
    first = _task(tmp_path)
    repository.add(first)
    conflicting_attempt = DownloadTask.create(
        task_id=TaskId.new(),
        attempt_id=first.current_attempt.attempt_id,
        request=first.request,
        created_at=_at(1),
    )

    with pytest.raises(TaskRepositoryConflict):
        repository.add(conflicting_attempt)

    assert repository.get(conflicting_attempt.task_id) is None
    assert repository.get(first.task_id) == first


def test_replace_integrity_conflict_rolls_back_original_task(tmp_path: Path) -> None:
    repository = SQLiteTaskRepository(tmp_path / "mediaflow.db")
    first = _task(tmp_path)
    failed = first.transition(
        TaskState.FAILED,
        at=_at(1),
        failure=Failure(FailureCategory.NETWORK, "network.timeout", retryable=True),
    )
    second = _task(tmp_path, created_at=_at(1))
    repository.add(failed)
    repository.add(second)
    updated = failed.retry(attempt_id=second.current_attempt.attempt_id, at=_at(2))

    with pytest.raises(TaskRepositoryConflict):
        repository.replace(expected=failed, updated=updated)

    assert repository.get(failed.task_id) == failed
    assert repository.get(second.task_id) == second


def _task(
    tmp_path: Path,
    *,
    preset: DownloadPreset | None = None,
    created_at: UtcTimestamp | None = None,
) -> DownloadTask:
    timestamp = created_at or _at(0)
    return DownloadTask.create(
        task_id=TaskId.new(),
        attempt_id=AttemptId.new(),
        request=DownloadRequest(
            source_url=SourceUrl("https://example.com/watch?v=123"),
            media_title="Example title",
            preset=preset or VideoPreset(),
            output_directory=OutputPath(tmp_path.resolve()),
        ),
        created_at=timestamp,
    )


def _at(minutes: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 9, 6, 10, tzinfo=UTC) + timedelta(minutes=minutes))
