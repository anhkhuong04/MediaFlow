from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from shutil import _ntuple_diskusage

import pytest

from mediaflow.application import (
    ConflictPolicy,
    DownloadArtifact,
    ProcessingJob,
)
from mediaflow.domain import (
    AttemptId,
    AudioContainer,
    AudioPreset,
    DownloadRequest,
    FailureCategory,
    OutputPath,
    ProgressSnapshot,
    SourceUrl,
    StreamKind,
    TaskId,
    UtcTimestamp,
    VideoContainer,
    VideoPreset,
)
from mediaflow.infrastructure.media import (
    FfmpegMediaProcessor,
    FfmpegProcessorOptions,
    ProcessResult,
    ProcessTermination,
    estimate_disk_space,
)


@dataclass(slots=True)
class Token:
    cancelled: bool = False

    def is_cancelled(self) -> bool:
        return self.cancelled


@dataclass(slots=True)
class Sink:
    fractions: list[float | None] = field(default_factory=list)

    def report(self, progress: ProgressSnapshot) -> None:
        fraction = progress.fraction
        assert isinstance(fraction, float)
        self.fractions.append(fraction)


@dataclass(slots=True)
class FakeRunner:
    results: list[ProcessResult] = field(default_factory=list)
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def run(
        self,
        arguments: tuple[str, ...],
        *,
        cancellation: object,
        timeout_seconds: float,
    ) -> ProcessResult:
        del cancellation
        assert timeout_seconds > 0
        self.calls.append(arguments)
        result = (
            self.results.pop(0)
            if self.results
            else ProcessResult(ProcessTermination.EXITED, exit_code=0)
        )
        if arguments[0] == "ffmpeg" and result.succeeded:
            Path(arguments[-1]).write_bytes(b"processed-media")
        return result


def test_merges_typed_video_audio_then_verifies_and_atomically_finalizes(
    tmp_path: Path,
) -> None:
    job = _video_job(tmp_path, container=VideoContainer.MP4)
    runner = FakeRunner()
    sink = Sink()

    outcome = _processor(runner).process(job, progress=sink, cancellation=Token())

    assert outcome.output_path is not None
    assert outcome.output_path.value.name == "A _ title.mp4"
    assert outcome.output_path.value.read_bytes() == b"processed-media"
    ffmpeg = runner.calls[0]
    assert ffmpeg[:6] == (
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-n",
    )
    assert ffmpeg.count("-i") == 2
    assert ffmpeg[10:12] == ("-map", "0:v:0")
    assert "-c:v" in ffmpeg and "-c:a" in ffmpeg
    assert runner.calls[1][0] == "ffprobe"
    assert sink.fractions == [0.0, 1.0]
    assert all(not path.value.exists() for path in job.artifact.paths)


@pytest.mark.parametrize(
    ("container", "codec"),
    [(AudioContainer.M4A, "aac"), (AudioContainer.MP3, "libmp3lame")],
)
def test_converts_audio_presets_with_explicit_argument_arrays(
    tmp_path: Path, container: AudioContainer, codec: str
) -> None:
    job = _audio_job(tmp_path, container=container)
    runner = FakeRunner()

    outcome = _processor(runner).process(job, progress=Sink(), cancellation=Token())

    assert outcome.output_path is not None
    assert outcome.output_path.value.suffix == f".{container.value}"
    assert "-vn" in runner.calls[0]
    assert codec in runner.calls[0]


def test_original_audio_is_copied_without_ffmpeg_but_still_verified(tmp_path: Path) -> None:
    job = _audio_job(tmp_path, container=AudioContainer.ORIGINAL)
    source_content = job.artifact.paths[0].value.read_bytes()
    runner = FakeRunner()

    outcome = _processor(runner).process(job, progress=Sink(), cancellation=Token())

    assert outcome.output_path is not None
    assert outcome.output_path.value.suffix == ".webm"
    assert outcome.output_path.value.read_bytes() == source_content
    assert [call[0] for call in runner.calls] == ["ffprobe"]


def test_rename_conflict_preserves_existing_file(tmp_path: Path) -> None:
    (tmp_path / "A _ title.mp4").write_bytes(b"existing")
    job = _video_job(tmp_path, container=VideoContainer.MP4)

    outcome = _processor(FakeRunner()).process(job, progress=Sink(), cancellation=Token())

    assert outcome.output_path is not None
    assert outcome.output_path.value.name == "A _ title (1).mp4"
    assert (tmp_path / "A _ title.mp4").read_bytes() == b"existing"


def test_replace_conflict_is_only_used_when_explicit(tmp_path: Path) -> None:
    existing = tmp_path / "A _ title.mkv"
    existing.write_bytes(b"existing")
    job = _video_job(tmp_path, container=VideoContainer.MKV, conflict_policy=ConflictPolicy.REPLACE)

    outcome = _processor(FakeRunner()).process(job, progress=Sink(), cancellation=Token())

    assert outcome.output_path is not None
    assert outcome.output_path.value == existing
    assert existing.read_bytes() == b"processed-media"


def test_skip_conflict_writes_nothing_and_retains_retry_inputs(tmp_path: Path) -> None:
    existing = tmp_path / "A _ title.mp4"
    existing.write_bytes(b"existing")
    job = _video_job(tmp_path, container=VideoContainer.MP4, conflict_policy=ConflictPolicy.SKIP)
    runner = FakeRunner()

    outcome = _processor(runner).process(job, progress=Sink(), cancellation=Token())

    assert outcome.failure is not None
    assert outcome.failure.category is FailureCategory.OUTPUT_CONFLICT
    assert existing.read_bytes() == b"existing"
    assert runner.calls == []
    assert all(path.value.exists() for path in job.artifact.paths)


def test_ffmpeg_failure_is_processing_error_and_keeps_downloaded_inputs(
    tmp_path: Path,
) -> None:
    job = _video_job(tmp_path, container=VideoContainer.MKV)
    runner = FakeRunner(
        [ProcessResult(ProcessTermination.EXITED, exit_code=2, stderr="raw failure")]
    )

    outcome = _processor(runner).process(job, progress=Sink(), cancellation=Token())

    assert outcome.failure is not None
    assert outcome.failure.category is FailureCategory.PROCESSING
    assert outcome.failure.code == "processing.ffmpeg_failed"
    assert all(path.value.exists() for path in job.artifact.paths)
    assert not list(tmp_path.glob(".mediaflow-*.mkv"))


def test_missing_ffmpeg_is_dependency_failure(tmp_path: Path) -> None:
    job = _video_job(tmp_path, container=VideoContainer.MP4)
    outcome = _processor(FakeRunner([ProcessResult(ProcessTermination.NOT_FOUND)])).process(
        job, progress=Sink(), cancellation=Token()
    )

    assert outcome.failure is not None
    assert outcome.failure.category is FailureCategory.DEPENDENCY
    assert outcome.failure.code == "processing.ffmpeg_unavailable"


def test_cancelled_ffmpeg_keeps_downloaded_inputs(tmp_path: Path) -> None:
    job = _video_job(tmp_path, container=VideoContainer.MP4)
    outcome = _processor(FakeRunner([ProcessResult(ProcessTermination.CANCELLED)])).process(
        job, progress=Sink(), cancellation=Token()
    )

    assert outcome.failure is not None
    assert outcome.failure.category is FailureCategory.CANCELLED
    assert all(path.value.exists() for path in job.artifact.paths)


def test_failed_ffprobe_prevents_publication_and_keeps_inputs(tmp_path: Path) -> None:
    job = _video_job(tmp_path, container=VideoContainer.MP4)
    runner = FakeRunner(
        [
            ProcessResult(ProcessTermination.EXITED, exit_code=0),
            ProcessResult(ProcessTermination.EXITED, exit_code=1),
        ]
    )

    outcome = _processor(runner).process(job, progress=Sink(), cancellation=Token())

    assert outcome.failure is not None
    assert outcome.failure.code == "processing.ffprobe_failed"
    assert not (tmp_path / "A _ title.mp4").exists()
    assert all(path.value.exists() for path in job.artifact.paths)


def test_disk_space_check_is_explicitly_an_estimate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _video_job(tmp_path, container=VideoContainer.MP4)
    monkeypatch.setattr(
        "mediaflow.infrastructure.media.ffmpeg_processor.shutil.disk_usage",
        lambda path: _ntuple_diskusage(total=100, used=99, free=1),
    )

    estimate = estimate_disk_space(job)
    outcome = _processor(FakeRunner()).process(job, progress=Sink(), cancellation=Token())

    assert estimate is not None and estimate.is_estimate
    assert not estimate.is_sufficient
    assert outcome.failure is not None
    assert outcome.failure.category is FailureCategory.DISK_SPACE
    assert outcome.failure.code == "processing.disk_space_estimate"
    assert all(path.value.exists() for path in job.artifact.paths)


def _processor(runner: FakeRunner) -> FfmpegMediaProcessor:
    return FfmpegMediaProcessor(
        runner,
        FfmpegProcessorOptions(
            ffmpeg_executable="ffmpeg",
            ffprobe_executable="ffprobe",
            process_timeout_seconds=10,
            probe_timeout_seconds=2,
        ),
        timestamp_factory=lambda: UtcTimestamp(datetime(2026, 9, 7, tzinfo=UTC)),
    )


_TASK_ID = TaskId.parse("00000000-0000-4000-8000-000000000010")
_ATTEMPT_ID = AttemptId.parse("00000000-0000-4000-8000-000000000020")


def _video_job(
    tmp_path: Path,
    *,
    container: VideoContainer,
    conflict_policy: ConflictPolicy = ConflictPolicy.RENAME,
) -> ProcessingJob:
    staging = tmp_path / ".mediaflow-staging" / str(_TASK_ID) / str(_ATTEMPT_ID)
    staging.mkdir(parents=True)
    video = staging / "video.webm"
    audio = staging / "audio.webm"
    video.write_bytes(b"video")
    audio.write_bytes(b"audio")
    return ProcessingJob(
        _TASK_ID,
        _ATTEMPT_ID,
        DownloadRequest(
            SourceUrl("https://example.com/watch/1"),
            "A : title",
            VideoPreset(container=container),
            OutputPath(tmp_path),
        ),
        DownloadArtifact(
            (OutputPath(video), OutputPath(audio)),
            True,
            (StreamKind.VIDEO, StreamKind.AUDIO),
        ),
        conflict_policy,
    )


def _audio_job(tmp_path: Path, *, container: AudioContainer) -> ProcessingJob:
    staging = tmp_path / ".mediaflow-staging" / str(_TASK_ID) / str(_ATTEMPT_ID)
    staging.mkdir(parents=True)
    audio = staging / "audio.webm"
    audio.write_bytes(b"audio-content")
    return ProcessingJob(
        _TASK_ID,
        _ATTEMPT_ID,
        DownloadRequest(
            SourceUrl("https://example.com/watch/1"),
            "Audio",
            AudioPreset(container=container),
            OutputPath(tmp_path),
        ),
        DownloadArtifact((OutputPath(audio),), True, (StreamKind.AUDIO,)),
    )
