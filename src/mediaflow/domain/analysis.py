"""Lifecycle for transient URL analysis, separate from download tasks."""

from dataclasses import dataclass
from enum import StrEnum

from mediaflow.domain.errors import Failure, FailureCategory
from mediaflow.domain.identifiers import SourceUrl, UtcTimestamp
from mediaflow.domain.media import MediaInfo


class AnalysisState(StrEnum):
    ANALYZING = "analyzing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InvalidAnalysisTransition(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AnalysisOperation:
    source_url: SourceUrl
    state: AnalysisState
    started_at: UtcTimestamp
    finished_at: UtcTimestamp | None = None
    result: MediaInfo | None = None
    failure: Failure | None = None

    def __post_init__(self) -> None:
        terminal = self.state is not AnalysisState.ANALYZING
        if terminal != (self.finished_at is not None):
            raise ValueError("Only terminal analysis operations must have a finished timestamp")
        if self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("Analysis cannot finish before it starts")
        if (self.state is AnalysisState.SUCCEEDED) != (self.result is not None):
            raise ValueError("Only successful analysis can contain media info")
        if (self.state is AnalysisState.FAILED) != (self.failure is not None):
            raise ValueError("Only failed analysis can contain a failure")

    @classmethod
    def start(cls, *, source_url: SourceUrl, at: UtcTimestamp) -> "AnalysisOperation":
        return cls(source_url=source_url, state=AnalysisState.ANALYZING, started_at=at)

    def succeed(self, *, media: MediaInfo, at: UtcTimestamp) -> "AnalysisOperation":
        self._ensure_active(at)
        return AnalysisOperation(
            source_url=self.source_url,
            state=AnalysisState.SUCCEEDED,
            started_at=self.started_at,
            finished_at=at,
            result=media,
        )

    def fail(self, *, failure: Failure, at: UtcTimestamp) -> "AnalysisOperation":
        self._ensure_active(at)
        if failure.category is FailureCategory.CANCELLED:
            raise ValueError("Use cancel for a cancelled analysis operation")
        return AnalysisOperation(
            source_url=self.source_url,
            state=AnalysisState.FAILED,
            started_at=self.started_at,
            finished_at=at,
            failure=failure,
        )

    def cancel(self, *, at: UtcTimestamp) -> "AnalysisOperation":
        self._ensure_active(at)
        return AnalysisOperation(
            source_url=self.source_url,
            state=AnalysisState.CANCELLED,
            started_at=self.started_at,
            finished_at=at,
        )

    def _ensure_active(self, at: UtcTimestamp) -> None:
        if self.state is not AnalysisState.ANALYZING:
            raise InvalidAnalysisTransition("Analysis operation is already terminal")
        if at < self.started_at:
            raise ValueError("Analysis cannot finish before it starts")
