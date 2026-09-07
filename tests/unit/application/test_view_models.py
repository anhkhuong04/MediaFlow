from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mediaflow.application import DownloadArtifact
from mediaflow.application.view_models import task_item_view
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
from tests.unit.application.fakes import FakeRecoveryStore


@dataclass(frozen=True, slots=True)
class FakeOutputInspector:
    exists_value: bool = False

    def exists(self, output_path: OutputPath) -> bool:
        del output_path
        return self.exists_value

    def remove(self, output_path: OutputPath) -> bool:
        del output_path
        return self.exists_value


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        ("queued", (True, False, False, False, False, False)),
        ("download_failed", (False, True, False, False, False, False)),
        ("processing_failed", (False, False, False, False, True, False)),
        ("interrupted", (True, False, True, True, False, False)),
        ("completed", (False, False, False, False, False, True)),
    ],
)
def test_task_actions_are_projected_from_state_and_real_recovery_data(
    scenario: str,
    expected: tuple[bool, bool, bool, bool, bool, bool],
    tmp_path: Path,
) -> None:
    task = _task(tmp_path)
    recovery = FakeRecoveryStore()
    output_files = FakeOutputInspector()
    if scenario == "download_failed":
        task = task.transition(
            TaskState.FAILED,
            at=_at(1),
            failure=Failure(FailureCategory.NETWORK, "download.network", True),
        )
    elif scenario == "processing_failed":
        task = task.transition(TaskState.DOWNLOADING, at=_at(1)).transition(
            TaskState.PROCESSING, at=_at(2)
        )
        task = task.transition(
            TaskState.FAILED,
            at=_at(3),
            failure=Failure(FailureCategory.PROCESSING, "processing.ffmpeg_failed", True),
        )
        recovery.artifact = DownloadArtifact((OutputPath(tmp_path / "input.webm"),), True)
    elif scenario == "interrupted":
        task = task.transition(TaskState.DOWNLOADING, at=_at(1)).transition(
            TaskState.INTERRUPTED, at=_at(2)
        )
        recovery.partial = True
    elif scenario == "completed":
        task = task.transition(TaskState.DOWNLOADING, at=_at(1)).transition(
            TaskState.COMPLETED,
            at=_at(2),
            output_path=OutputPath(tmp_path / "final.mp4"),
        )
        output_files = FakeOutputInspector(True)

    actions = task_item_view(task, recovery_store=recovery, output_files=output_files).actions

    assert (
        actions.can_cancel,
        actions.can_retry,
        actions.can_resume,
        actions.can_restart,
        actions.can_retry_processing,
        actions.can_open_output,
    ) == expected


def _task(tmp_path: Path) -> DownloadTask:
    return DownloadTask.create(
        task_id=TaskId.new(),
        attempt_id=AttemptId.new(),
        request=DownloadRequest(
            SourceUrl("https://example.com/media"),
            "Media",
            VideoPreset(),
            OutputPath(tmp_path),
        ),
        created_at=_at(0),
    )


def _at(seconds: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 9, 7, tzinfo=UTC) + timedelta(seconds=seconds))
