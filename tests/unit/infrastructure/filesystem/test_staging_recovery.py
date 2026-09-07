from datetime import UTC, datetime
from pathlib import Path

from mediaflow.application import CleanupDisposition, DownloadArtifact
from mediaflow.domain import (
    AttemptId,
    DownloadRequest,
    DownloadTask,
    OutputPath,
    SourceUrl,
    StreamKind,
    TaskId,
    UtcTimestamp,
    VideoPreset,
)
from mediaflow.infrastructure.filesystem import StagingRecoveryStore, write_artifact_manifest


def test_partial_resume_requires_nonempty_real_part_file(tmp_path: Path) -> None:
    task = _task(tmp_path)
    directory = _directory(task)
    directory.mkdir(parents=True)
    (directory / "empty.webm.part").touch()
    store = StagingRecoveryStore()
    assert not store.has_resumable_partial(task)

    (directory / "video.webm.part").write_bytes(b"partial")
    assert store.has_resumable_partial(task)


def test_manifest_round_trip_rejects_missing_inputs_and_success_cleanup_only(
    tmp_path: Path,
) -> None:
    task = _task(tmp_path)
    directory = _directory(task)
    directory.mkdir(parents=True)
    input_path = directory / "video.webm"
    input_path.write_bytes(b"media")
    artifact = DownloadArtifact((OutputPath(input_path),), True, (StreamKind.AUDIO_VIDEO,))
    write_artifact_manifest(directory, artifact)
    store = StagingRecoveryStore()

    assert store.load_processing_artifact(task) == artifact
    store.cleanup(task, CleanupDisposition.INTERRUPTED)
    assert directory.exists()
    input_path.unlink()
    assert store.load_processing_artifact(task) is None

    input_path.write_bytes(b"media")
    store.cleanup(task, CleanupDisposition.SUCCESS)
    assert not directory.exists()


def _task(tmp_path: Path) -> DownloadTask:
    return DownloadTask.create(
        task_id=TaskId.new(),
        attempt_id=AttemptId.new(),
        request=DownloadRequest(
            SourceUrl("https://example.com/video"),
            "Video",
            VideoPreset(),
            OutputPath(tmp_path),
        ),
        created_at=UtcTimestamp(datetime(2026, 9, 7, tzinfo=UTC)),
    )


def _directory(task: DownloadTask) -> Path:
    return (
        task.request.output_directory.value
        / ".mediaflow-staging"
        / str(task.task_id)
        / str(task.current_attempt.attempt_id)
    )
