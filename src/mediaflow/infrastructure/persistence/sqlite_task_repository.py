"""SQLite implementation of the application-owned task repository port."""

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import cast

from mediaflow.application import TaskRepositoryConflict
from mediaflow.domain import (
    TERMINAL_STATES,
    AttemptId,
    AudioContainer,
    AudioPreset,
    AudioQuality,
    DownloadAttempt,
    DownloadPreset,
    DownloadRequest,
    DownloadTask,
    Failure,
    FailureCategory,
    OutputPath,
    SourceUrl,
    TaskId,
    TaskState,
    UtcTimestamp,
    VideoContainer,
    VideoPreset,
    VideoQuality,
)
from mediaflow.infrastructure.persistence.migrations import MigrationRunner


class CorruptTaskData(RuntimeError):
    """Persisted task data violates the domain contract."""


class SQLiteTaskRepository:
    """Persist durable task facts with an explicit progress checkpoint policy.

    Progress snapshots, byte counts, speed, and ETA are transient and omitted.
    ``updated_at`` remains durable, recording the last checkpoint without storing
    high-frequency telemetry.
    """

    def __init__(self, database_path: Path, *, migrate: bool = True) -> None:
        self._database_path = database_path
        if migrate:
            MigrationRunner(database_path).migrate()

    def add(self, task: DownloadTask) -> None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._insert_task(connection, task)
            connection.commit()
        except sqlite3.IntegrityError as error:
            connection.rollback()
            raise TaskRepositoryConflict(f"Task {task.task_id} already exists") from error
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get(self, task_id: TaskId) -> DownloadTask | None:
        with closing(self._connect()) as connection:
            return self._load_task(connection, task_id)

    def replace(self, *, expected: DownloadTask, updated: DownloadTask) -> None:
        if updated.task_id != expected.task_id:
            raise TaskRepositoryConflict("Updated task ID differs from the expected aggregate")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            stored = self._load_task(connection, expected.task_id)
            if stored is None or _durable_fingerprint(stored) != _durable_fingerprint(expected):
                raise TaskRepositoryConflict("Stored task no longer matches the expected aggregate")
            connection.execute(
                "DELETE FROM download_tasks WHERE task_id = ?", (str(expected.task_id),)
            )
            self._insert_task(connection, updated)
            connection.commit()
        except sqlite3.IntegrityError as error:
            connection.rollback()
            raise TaskRepositoryConflict("Updated task conflicts with persisted data") from error
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_downloads(self) -> tuple[DownloadTask, ...]:
        return self._list_tasks(
            "SELECT task_id FROM download_tasks ORDER BY created_at_utc DESC, task_id DESC"
        )

    def list_history(self) -> tuple[DownloadTask, ...]:
        terminal_values = tuple(state.value for state in TERMINAL_STATES)
        placeholders = ", ".join("?" for _ in terminal_values)
        query = f"""
            SELECT tasks.task_id
            FROM download_tasks AS tasks
            JOIN download_attempts AS attempts
              ON attempts.task_id = tasks.task_id
             AND attempts.attempt_number = (
                 SELECT MAX(current_attempt.attempt_number)
                 FROM download_attempts AS current_attempt
                 WHERE current_attempt.task_id = tasks.task_id
             )
            WHERE attempts.state IN ({placeholders})
            ORDER BY attempts.finished_at_utc DESC, tasks.task_id DESC
        """
        return self._list_tasks(query, terminal_values)

    def _list_tasks(self, query: str, parameters: tuple[str, ...] = ()) -> tuple[DownloadTask, ...]:
        with closing(self._connect()) as connection:
            task_ids = tuple(
                TaskId.parse(cast(str, row[0]))
                for row in connection.execute(query, parameters).fetchall()
            )
            tasks: list[DownloadTask] = []
            for task_id in task_ids:
                task = self._load_task(connection, task_id)
                if task is None:
                    raise CorruptTaskData(f"Task {task_id} disappeared while reading")
                tasks.append(task)
            return tuple(tasks)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, isolation_level=None)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @staticmethod
    def _insert_task(connection: sqlite3.Connection, task: DownloadTask) -> None:
        preset_kind, preset_quality, preset_container, preset_fps = _serialize_preset(
            task.request.preset
        )
        connection.execute(
            """
            INSERT INTO download_tasks(
                task_id, source_url, media_title, preset_kind, preset_quality,
                preset_container, preset_fps, output_directory, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(task.task_id),
                str(task.request.source_url),
                task.request.media_title,
                preset_kind,
                preset_quality,
                preset_container,
                preset_fps,
                str(task.request.output_directory),
                _serialize_timestamp(task.created_at),
            ),
        )
        for attempt in task.attempts:
            failure = attempt.failure
            connection.execute(
                """
                INSERT INTO download_attempts(
                    attempt_id, task_id, attempt_number, state, created_at_utc,
                    updated_at_utc, finished_at_utc, failure_category, failure_code,
                    failure_retryable
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(attempt.attempt_id),
                    str(task.task_id),
                    attempt.number,
                    attempt.state.value,
                    _serialize_timestamp(attempt.created_at),
                    _serialize_timestamp(attempt.updated_at),
                    _serialize_optional_timestamp(attempt.finished_at),
                    failure.category.value if failure is not None else None,
                    failure.code if failure is not None else None,
                    int(failure.retryable) if failure is not None else None,
                ),
            )
            if attempt.output_path is not None:
                connection.execute(
                    "INSERT INTO task_outputs(attempt_id, output_path) VALUES (?, ?)",
                    (str(attempt.attempt_id), str(attempt.output_path)),
                )

    @staticmethod
    def _load_task(connection: sqlite3.Connection, task_id: TaskId) -> DownloadTask | None:
        task_row = connection.execute(
            """
            SELECT source_url, media_title, preset_kind, preset_quality, preset_container,
                   preset_fps, output_directory, created_at_utc
            FROM download_tasks WHERE task_id = ?
            """,
            (str(task_id),),
        ).fetchone()
        if task_row is None:
            return None
        attempt_rows = connection.execute(
            """
            SELECT attempts.attempt_id, attempts.attempt_number, attempts.state,
                   attempts.created_at_utc, attempts.updated_at_utc,
                   attempts.finished_at_utc, attempts.failure_category,
                   attempts.failure_code, attempts.failure_retryable, outputs.output_path
            FROM download_attempts AS attempts
            LEFT JOIN task_outputs AS outputs ON outputs.attempt_id = attempts.attempt_id
            WHERE attempts.task_id = ?
            ORDER BY attempts.attempt_number
            """,
            (str(task_id),),
        ).fetchall()
        try:
            source_url = cast(str, task_row[0])
            title = cast(str, task_row[1])
            preset = _deserialize_preset(
                kind=cast(str, task_row[2]),
                quality=cast(str, task_row[3]),
                container=cast(str, task_row[4]),
                frames_per_second=cast(int | None, task_row[5]),
            )
            request = DownloadRequest(
                source_url=SourceUrl(source_url),
                media_title=title,
                preset=preset,
                output_directory=OutputPath(Path(cast(str, task_row[6]))),
            )
            attempts = tuple(_deserialize_attempt(row) for row in attempt_rows)
            return DownloadTask(
                task_id=task_id,
                request=request,
                created_at=_deserialize_timestamp(cast(str, task_row[7])),
                attempts=attempts,
            )
        except (TypeError, ValueError) as error:
            raise CorruptTaskData(f"Task {task_id} contains invalid persisted data") from error


def _serialize_preset(preset: DownloadPreset) -> tuple[str, str, str, int | None]:
    if isinstance(preset, VideoPreset):
        return (
            "video",
            preset.quality.value,
            preset.container.value,
            preset.preferred_frames_per_second,
        )
    if isinstance(preset, AudioPreset):
        return "audio", preset.quality.value, preset.container.value, None
    raise TypeError(f"Unsupported preset type: {type(preset).__name__}")


def _deserialize_preset(
    *, kind: str, quality: str, container: str, frames_per_second: int | None
) -> DownloadPreset:
    if kind == "video":
        return VideoPreset(
            quality=VideoQuality(quality),
            container=VideoContainer(container),
            preferred_frames_per_second=frames_per_second,
        )
    if kind == "audio":
        if frames_per_second is not None:
            raise ValueError("Audio preset cannot contain a frame rate")
        return AudioPreset(quality=AudioQuality(quality), container=AudioContainer(container))
    raise ValueError(f"Unknown preset kind: {kind}")


def _deserialize_attempt(row: tuple[object, ...]) -> DownloadAttempt:
    failure_category = cast(str | None, row[6])
    failure_code = cast(str | None, row[7])
    failure_retryable = cast(int | None, row[8])
    failure_values = (failure_category, failure_code, failure_retryable)
    if any(value is None for value in failure_values) and any(
        value is not None for value in failure_values
    ):
        raise ValueError("Persisted failure fields must be all present or all absent")
    failure = None
    if failure_category is not None and failure_code is not None and failure_retryable is not None:
        failure = Failure(
            category=FailureCategory(failure_category),
            code=failure_code,
            retryable=bool(failure_retryable),
        )
    finished_at = cast(str | None, row[5])
    output_path = cast(str | None, row[9])
    return DownloadAttempt(
        attempt_id=AttemptId.parse(cast(str, row[0])),
        number=cast(int, row[1]),
        state=TaskState(cast(str, row[2])),
        created_at=_deserialize_timestamp(cast(str, row[3])),
        updated_at=_deserialize_timestamp(cast(str, row[4])),
        finished_at=_deserialize_timestamp(finished_at) if finished_at is not None else None,
        failure=failure,
        output_path=OutputPath(Path(output_path)) if output_path is not None else None,
    )


def _serialize_timestamp(timestamp: UtcTimestamp) -> str:
    return timestamp.value.isoformat(timespec="microseconds")


def _serialize_optional_timestamp(timestamp: UtcTimestamp | None) -> str | None:
    return _serialize_timestamp(timestamp) if timestamp is not None else None


def _deserialize_timestamp(value: str) -> UtcTimestamp:
    from datetime import datetime

    return UtcTimestamp(datetime.fromisoformat(value))


def _durable_fingerprint(task: DownloadTask) -> tuple[object, ...]:
    """Compare the persisted subset, intentionally excluding progress telemetry."""

    return (
        task.task_id,
        task.request,
        task.created_at,
        tuple(
            (
                attempt.attempt_id,
                attempt.number,
                attempt.state,
                attempt.created_at,
                attempt.updated_at,
                attempt.finished_at,
                attempt.failure,
                attempt.output_path,
            )
            for attempt in task.attempts
        ),
    )
