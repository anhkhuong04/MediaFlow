"""FFmpeg processing, output verification, and safe finalization."""

import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from mediaflow.application import (
    CancellationToken,
    ConflictPolicy,
    DiskSpaceEstimate,
    ProcessingJob,
    ProcessingOutcome,
    ProgressSink,
)
from mediaflow.domain import (
    AudioContainer,
    AudioPreset,
    Failure,
    FailureCategory,
    OutputPath,
    ProgressSnapshot,
    StreamKind,
    UtcTimestamp,
    VideoContainer,
    VideoPreset,
)
from mediaflow.infrastructure.filesystem import (
    OutputConflictError,
    OutputPathError,
    WindowsPathPolicy,
    publish_atomic,
    select_output_path,
    temporary_output_path,
)
from mediaflow.infrastructure.media.process_runner import (
    ProcessResult,
    ProcessRunner,
    ProcessTermination,
)

_LOGGER = logging.getLogger("mediaflow.processing")
_DEFAULT_PATH_POLICY = WindowsPathPolicy()


@dataclass(frozen=True, slots=True)
class FfmpegProcessorOptions:
    ffmpeg_executable: str = "ffmpeg"
    ffprobe_executable: str = "ffprobe"
    process_timeout_seconds: float = 3600.0
    probe_timeout_seconds: float = 30.0
    path_policy: WindowsPathPolicy = _DEFAULT_PATH_POLICY

    def __post_init__(self) -> None:
        for executable in (self.ffmpeg_executable, self.ffprobe_executable):
            if not executable or "\0" in executable:
                raise ValueError("Media executable must be non-empty")
        if self.process_timeout_seconds <= 0 or self.probe_timeout_seconds <= 0:
            raise ValueError("Media process timeouts must be positive")


@dataclass(frozen=True, slots=True)
class FfmpegMediaProcessor:
    runner: ProcessRunner
    options: FfmpegProcessorOptions = FfmpegProcessorOptions()
    timestamp_factory: Callable[[], UtcTimestamp] = UtcTimestamp.now

    def process(
        self,
        job: ProcessingJob,
        *,
        progress: ProgressSink,
        cancellation: CancellationToken,
    ) -> ProcessingOutcome:
        if cancellation.is_cancelled():
            return _cancelled()
        try:
            inputs = self._validated_inputs(job)
            job.request.output_directory.value.mkdir(parents=True, exist_ok=True)
            estimate = estimate_disk_space(job)
            if estimate is not None and not estimate.is_sufficient:
                return ProcessingOutcome.failed(
                    Failure(
                        FailureCategory.DISK_SPACE,
                        "processing.disk_space_estimate",
                        retryable=True,
                    )
                )
            extension = _output_extension(job, inputs)
            final_path = select_output_path(
                job.request.output_directory,
                title=job.request.media_title,
                extension=extension,
                conflict_policy=job.conflict_policy,
                path_policy=self.options.path_policy,
            )
            temporary_path = temporary_output_path(final_path)
            self._report(progress, fraction=0.0)
            if isinstance(job.request.preset, AudioPreset) and (
                job.request.preset.container is AudioContainer.ORIGINAL
            ):
                copy_result = _copy_file(inputs[0], temporary_path.value, cancellation=cancellation)
                if copy_result is not None:
                    return copy_result
            else:
                command = self._build_ffmpeg_command(job, inputs, temporary_path.value)
                process_result = self.runner.run(
                    command,
                    cancellation=cancellation,
                    timeout_seconds=self.options.process_timeout_seconds,
                )
                failure = _map_process_failure(process_result, tool="ffmpeg")
                if failure is not None:
                    _remove_owned_temporary(temporary_path.value)
                    return ProcessingOutcome.failed(failure)
            verification_failure = self._verify(temporary_path, cancellation)
            if verification_failure is not None:
                _remove_owned_temporary(temporary_path.value)
                return ProcessingOutcome.failed(verification_failure)
            if cancellation.is_cancelled():
                _remove_owned_temporary(temporary_path.value)
                return _cancelled()
            final_path = self._publish(job, temporary_path, final_path, extension)
            if not final_path.value.is_file() or final_path.value.stat().st_size <= 0:
                return ProcessingOutcome.failed(
                    Failure(
                        FailureCategory.PROCESSING,
                        "processing.final_verification_failed",
                        retryable=True,
                    )
                )
            self._cleanup_inputs(job, inputs)
            self._report(progress, fraction=1.0)
            return ProcessingOutcome.succeeded(final_path)
        except OutputConflictError:
            return ProcessingOutcome.failed(
                Failure(
                    FailureCategory.OUTPUT_CONFLICT,
                    "processing.output_conflict",
                    retryable=True,
                )
            )
        except OSError as error:
            return ProcessingOutcome.failed(_filesystem_failure(error))
        except (OutputPathError, ValueError):
            return ProcessingOutcome.failed(
                Failure(
                    FailureCategory.PROCESSING,
                    "processing.filesystem",
                    retryable=True,
                )
            )

    def _validated_inputs(self, job: ProcessingJob) -> tuple[Path, ...]:
        staging_root = (
            job.request.output_directory.value / ".mediaflow-staging" / str(job.task_id)
        ).resolve(strict=False)
        paths = tuple(item.value.resolve(strict=False) for item in job.artifact.paths)
        if any(
            not path.is_relative_to(staging_root) or not path.is_file() or path.stat().st_size <= 0
            for path in paths
        ):
            raise ValueError("Processing inputs must be non-empty attempt staging files")
        preset = job.request.preset
        kinds = job.artifact.stream_kinds
        if not kinds and len(paths) == 1:
            kinds = (StreamKind.AUDIO_VIDEO,)
        elif not kinds and len(paths) == 2:
            # The downloader selector orders separate video before audio.
            kinds = (StreamKind.VIDEO, StreamKind.AUDIO)
        if isinstance(preset, VideoPreset):
            if len(paths) == 1 and kinds == (StreamKind.AUDIO_VIDEO,):
                return paths
            if len(paths) == 2 and set(kinds) == {StreamKind.VIDEO, StreamKind.AUDIO}:
                video = paths[kinds.index(StreamKind.VIDEO)]
                audio = paths[kinds.index(StreamKind.AUDIO)]
                return video, audio
            raise ValueError("Video processing requires typed video and audio inputs")
        if len(paths) != 1 or (
            kinds and kinds[0] not in {StreamKind.AUDIO, StreamKind.AUDIO_VIDEO}
        ):
            raise ValueError("Audio processing requires one audio-capable input")
        return paths

    def _build_ffmpeg_command(
        self, job: ProcessingJob, inputs: tuple[Path, ...], output: Path
    ) -> tuple[str, ...]:
        common = (
            self.options.ffmpeg_executable,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-n",
        )
        preset = job.request.preset
        if isinstance(preset, VideoPreset):
            arguments = [*common, "-i", str(inputs[0])]
            if len(inputs) == 2:
                arguments.extend(("-i", str(inputs[1]), "-map", "0:v:0", "-map", "1:a:0"))
            else:
                arguments.extend(("-map", "0:v:0", "-map", "0:a:0"))
            arguments.extend(("-c:v", "copy"))
            if preset.container is VideoContainer.MP4:
                arguments.extend(("-c:a", "aac", "-movflags", "+faststart"))
            else:
                arguments.extend(("-c:a", "copy"))
            arguments.append(str(output))
            return tuple(arguments)
        if preset.container is AudioContainer.M4A:
            codec_arguments = ("-vn", "-c:a", "aac", "-b:a", "192k")
        elif preset.container is AudioContainer.MP3:
            codec_arguments = ("-vn", "-c:a", "libmp3lame", "-q:a", "2")
        else:
            raise ValueError("Original audio does not require FFmpeg")
        return (*common, "-i", str(inputs[0]), *codec_arguments, str(output))

    def _verify(
        self, temporary_path: OutputPath, cancellation: CancellationToken
    ) -> Failure | None:
        if not temporary_path.value.is_file() or temporary_path.value.stat().st_size <= 0:
            return Failure(
                FailureCategory.PROCESSING,
                "processing.empty_output",
                retryable=True,
            )
        result = self.runner.run(
            (
                self.options.ffprobe_executable,
                "-v",
                "error",
                "-show_entries",
                "format=format_name,duration",
                "-of",
                "json",
                str(temporary_path.value),
            ),
            cancellation=cancellation,
            timeout_seconds=self.options.probe_timeout_seconds,
        )
        return _map_process_failure(result, tool="ffprobe")

    def _publish(
        self,
        job: ProcessingJob,
        temporary_path: OutputPath,
        final_path: OutputPath,
        extension: str,
    ) -> OutputPath:
        for _ in range(100):
            try:
                publish_atomic(
                    temporary_path,
                    final_path,
                    conflict_policy=job.conflict_policy,
                )
                return final_path
            except OutputConflictError:
                if job.conflict_policy is not ConflictPolicy.RENAME:
                    raise
                final_path = select_output_path(
                    job.request.output_directory,
                    title=job.request.media_title,
                    extension=extension,
                    conflict_policy=ConflictPolicy.RENAME,
                    path_policy=self.options.path_policy,
                )
        raise OutputConflictError("Output kept changing during atomic publication")

    def _cleanup_inputs(self, job: ProcessingJob, inputs: tuple[Path, ...]) -> None:
        staging_root = (job.request.output_directory.value / ".mediaflow-staging").resolve(
            strict=False
        )
        for path in inputs:
            if not path.is_relative_to(staging_root):
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError:
                _LOGGER.warning("application.failed")

    def _report(self, progress: ProgressSink, *, fraction: float) -> None:
        try:
            progress.report(
                ProgressSnapshot.processing(captured_at=self.timestamp_factory(), fraction=fraction)
            )
        except Exception:
            _LOGGER.warning("application.failed")


def estimate_disk_space(job: ProcessingJob) -> DiskSpaceEstimate | None:
    try:
        required = sum(path.value.stat().st_size for path in job.artifact.paths)
        available = shutil.disk_usage(job.request.output_directory.value).free
    except OSError:
        return None
    return DiskSpaceEstimate(required_bytes=required, available_bytes=available)


def _output_extension(job: ProcessingJob, inputs: tuple[Path, ...]) -> str:
    preset = job.request.preset
    if isinstance(preset, VideoPreset):
        return preset.container.value
    if preset.container is not AudioContainer.ORIGINAL:
        return preset.container.value
    extension = inputs[0].suffix.casefold().lstrip(".")
    return extension if extension.isalnum() else "m4a"


def _copy_file(
    source: Path, destination: Path, *, cancellation: CancellationToken
) -> ProcessingOutcome | None:
    try:
        with source.open("rb") as source_file, destination.open("xb") as destination_file:
            while block := source_file.read(1024 * 1024):
                if cancellation.is_cancelled():
                    destination_file.close()
                    _remove_owned_temporary(destination)
                    return _cancelled()
                destination_file.write(block)
    except OSError as error:
        _remove_owned_temporary(destination)
        return ProcessingOutcome.failed(_filesystem_failure(error, copy=True))
    return None


def _map_process_failure(result: ProcessResult, *, tool: str) -> Failure | None:
    if result.succeeded:
        return None
    if result.termination is ProcessTermination.CANCELLED:
        return Failure(FailureCategory.CANCELLED, "processing.cancelled", False)
    if result.termination is ProcessTermination.NOT_FOUND:
        return Failure(
            FailureCategory.DEPENDENCY,
            f"processing.{tool}_unavailable",
            retryable=True,
        )
    if result.termination is ProcessTermination.START_FAILED:
        return Failure(
            FailureCategory.DEPENDENCY,
            f"processing.{tool}_unusable",
            retryable=True,
        )
    if result.termination is ProcessTermination.TIMED_OUT:
        return Failure(
            FailureCategory.PROCESSING,
            f"processing.{tool}_timeout",
            retryable=True,
        )
    if "no space left" in result.stderr.casefold() or "disk full" in result.stderr.casefold():
        return Failure(
            FailureCategory.DISK_SPACE,
            "processing.disk_space",
            retryable=True,
        )
    return Failure(
        FailureCategory.PROCESSING,
        f"processing.{tool}_failed",
        retryable=True,
    )


def _cancelled() -> ProcessingOutcome:
    return ProcessingOutcome.failed(
        Failure(FailureCategory.CANCELLED, "processing.cancelled", False)
    )


def _filesystem_failure(error: OSError, *, copy: bool = False) -> Failure:
    if error.errno == 28:
        return Failure(
            FailureCategory.DISK_SPACE,
            "processing.disk_space",
            retryable=True,
        )
    code = "processing.copy_failed" if copy else "processing.filesystem"
    return Failure(FailureCategory.PROCESSING, code, retryable=True)


def _remove_owned_temporary(path: Path) -> None:
    try:
        if path.name.startswith(".mediaflow-"):
            path.unlink(missing_ok=True)
    except OSError:
        _LOGGER.warning("application.failed")
