"""Typed application boundary values shared with infrastructure adapters."""

from dataclasses import dataclass
from enum import StrEnum

from mediaflow.domain import (
    AttemptId,
    DownloadPreset,
    DownloadRequest,
    Failure,
    MediaInfo,
    OutputPath,
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

    def __post_init__(self) -> None:
        object.__setattr__(self, "paths", tuple(self.paths))
        if not self.paths:
            raise ValueError("A download artifact must contain at least one path")
        if len(set(self.paths)) != len(self.paths):
            raise ValueError("Download artifact paths must be unique")


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


@dataclass(frozen=True, slots=True)
class ApplicationSettings:
    default_output_directory: OutputPath
    default_preset: DownloadPreset = VideoPreset()
    concurrent_downloads: int = 2

    def __post_init__(self) -> None:
        if self.concurrent_downloads < 1:
            raise ValueError("Concurrent downloads must be positive")
