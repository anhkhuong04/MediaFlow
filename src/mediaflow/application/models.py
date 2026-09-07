"""Typed application boundary values shared with infrastructure adapters."""

from dataclasses import dataclass
from enum import StrEnum

from mediaflow.domain import (
    AttemptId,
    DownloadPreset,
    DownloadRequest,
    DownloadTask,
    Failure,
    MediaInfo,
    OutputPath,
    StreamKind,
    TaskId,
    VideoPreset,
)


@dataclass(frozen=True, slots=True)
class AnalysisOutcome:
    """Exactly one normalized media result or sanitized failure."""

    media: MediaInfo | None = None
    failure: Failure | None = None

    def __post_init__(self) -> None:
        if (self.media is None) == (self.failure is None):
            raise ValueError("Analysis outcome must contain exactly one result")

    @classmethod
    def succeeded(cls, media: MediaInfo) -> "AnalysisOutcome":
        return cls(media=media)

    @classmethod
    def failed(cls, failure: Failure) -> "AnalysisOutcome":
        return cls(failure=failure)


@dataclass(frozen=True, slots=True)
class DownloadArtifact:
    """Temporary or directly usable files produced by a downloader adapter."""

    paths: tuple[OutputPath, ...]
    requires_processing: bool
    stream_kinds: tuple[StreamKind, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "paths", tuple(self.paths))
        object.__setattr__(self, "stream_kinds", tuple(self.stream_kinds))
        if not self.paths:
            raise ValueError("A download artifact must contain at least one path")
        if len(set(self.paths)) != len(self.paths):
            raise ValueError("Download artifact paths must be unique")
        if self.stream_kinds and len(self.stream_kinds) != len(self.paths):
            raise ValueError("Stream kinds must align with artifact paths")


@dataclass(frozen=True, slots=True)
class DownloadJob:
    task_id: TaskId
    attempt_id: AttemptId
    request: DownloadRequest


@dataclass(frozen=True, slots=True)
class DownloadOutcome:
    artifact: DownloadArtifact | None = None
    failure: Failure | None = None

    def __post_init__(self) -> None:
        if (self.artifact is None) == (self.failure is None):
            raise ValueError("Download outcome must contain exactly one result")

    @classmethod
    def succeeded(cls, artifact: DownloadArtifact) -> "DownloadOutcome":
        return cls(artifact=artifact)

    @classmethod
    def failed(cls, failure: Failure) -> "DownloadOutcome":
        return cls(failure=failure)


class PartialFilePolicy(StrEnum):
    """C5 keeps partial files so cooperative resume remains possible."""

    KEEP = "keep"


class ResumeMode(StrEnum):
    DOWNLOAD = "download"
    PROCESSING = "processing"


class CleanupDisposition(StrEnum):
    SUCCESS = "success"
    CANCELLED = "cancelled"
    FAILURE = "failure"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class ResumePlan:
    task: DownloadTask
    mode: ResumeMode
    artifact: DownloadArtifact | None = None

    def __post_init__(self) -> None:
        if (self.mode is ResumeMode.PROCESSING) != (self.artifact is not None):
            raise ValueError("Only a processing resume plan requires an artifact")


@dataclass(frozen=True, slots=True)
class ShutdownReport:
    clean: bool
    interrupted_task_ids: tuple[TaskId, ...]
    queued_task_ids: tuple[TaskId, ...]


class ConflictPolicy(StrEnum):
    RENAME = "rename"
    SKIP = "skip"
    REPLACE = "replace"


@dataclass(frozen=True, slots=True)
class ProcessingJob:
    task_id: TaskId
    attempt_id: AttemptId
    request: DownloadRequest
    artifact: DownloadArtifact
    conflict_policy: ConflictPolicy = ConflictPolicy.RENAME


@dataclass(frozen=True, slots=True)
class ProcessingOutcome:
    output_path: OutputPath | None = None
    failure: Failure | None = None

    def __post_init__(self) -> None:
        if (self.output_path is None) == (self.failure is None):
            raise ValueError("Processing outcome must contain exactly one result")

    @classmethod
    def succeeded(cls, output_path: OutputPath) -> "ProcessingOutcome":
        return cls(output_path=output_path)

    @classmethod
    def failed(cls, failure: Failure) -> "ProcessingOutcome":
        return cls(failure=failure)


@dataclass(frozen=True, slots=True)
class DiskSpaceEstimate:
    """Estimated output requirement compared with a point-in-time free-space value."""

    required_bytes: int
    available_bytes: int
    is_estimate: bool = True

    def __post_init__(self) -> None:
        if self.required_bytes < 0 or self.available_bytes < 0:
            raise ValueError("Disk-space byte values cannot be negative")
        if not self.is_estimate:
            raise ValueError("C6 disk-space checks are estimates")

    @property
    def is_sufficient(self) -> bool:
        return self.available_bytes >= self.required_bytes


class DependencyComponent(StrEnum):
    YT_DLP = "yt-dlp"
    FFMPEG = "ffmpeg"
    FFPROBE = "ffprobe"


class DependencyState(StrEnum):
    READY = "ready"
    NOT_FOUND = "not_found"
    UNUSABLE = "unusable"


@dataclass(frozen=True, slots=True)
class DependencyInfo:
    component: DependencyComponent
    state: DependencyState
    version: str | None = None

    def __post_init__(self) -> None:
        if self.state is DependencyState.READY and not self.version:
            raise ValueError("A ready dependency requires a version")
        if self.state is not DependencyState.READY and self.version is not None:
            raise ValueError("An unavailable dependency cannot expose a version")


@dataclass(frozen=True, slots=True)
class DependencyReport:
    dependencies: tuple[DependencyInfo, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "dependencies", tuple(self.dependencies))
        components = tuple(item.component for item in self.dependencies)
        if set(components) != set(DependencyComponent) or len(components) != len(
            DependencyComponent
        ):
            raise ValueError("Dependency report must contain each component exactly once")


@dataclass(frozen=True, slots=True)
class ApplicationSettings:
    default_output_directory: OutputPath
    default_preset: DownloadPreset = VideoPreset()
    concurrent_downloads: int = 2

    def __post_init__(self) -> None:
        if self.concurrent_downloads < 1:
            raise ValueError("Concurrent downloads must be positive")
