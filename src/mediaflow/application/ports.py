"""Ports owned by the application core and implemented by adapters.

Analyzer, downloader, and processor calls may block. Their callers must schedule
them away from the presentation thread; these protocols deliberately contain no
Qt concepts.
"""

from typing import Protocol

from mediaflow.application.events import ApplicationEvent
from mediaflow.application.models import (
    AnalysisOutcome,
    ApplicationSettings,
    CleanupDisposition,
    DependencyReport,
    DownloadArtifact,
    DownloadJob,
    DownloadOutcome,
    ProcessingJob,
    ProcessingOutcome,
)
from mediaflow.domain import DownloadTask, ProgressSnapshot, SourceUrl, TaskId, UtcTimestamp


class TaskRepositoryConflict(RuntimeError):
    """The stored aggregate no longer matches the command's expected version."""


class CancellationToken(Protocol):
    def is_cancelled(self) -> bool: ...


class ProgressSink(Protocol):
    def report(self, progress: ProgressSnapshot) -> None: ...


class Analyzer(Protocol):
    def analyze(
        self, source_url: SourceUrl, *, cancellation: CancellationToken
    ) -> AnalysisOutcome: ...


class Downloader(Protocol):
    def download(
        self,
        job: DownloadJob,
        *,
        progress: ProgressSink,
        cancellation: CancellationToken,
    ) -> DownloadOutcome: ...


class MediaProcessor(Protocol):
    def process(
        self,
        job: ProcessingJob,
        *,
        progress: ProgressSink,
        cancellation: CancellationToken,
    ) -> ProcessingOutcome: ...


class DependencyProbe(Protocol):
    def probe(self) -> DependencyReport: ...


class RecoveryStore(Protocol):
    """Inspect and clean only app-owned attempt staging data."""

    def has_resumable_partial(self, task: DownloadTask) -> bool: ...

    def load_processing_artifact(self, task: DownloadTask) -> DownloadArtifact | None: ...

    def cleanup(self, task: DownloadTask, disposition: CleanupDisposition) -> None: ...


class TaskRepository(Protocol):
    """Durable task store with optimistic aggregate replacement."""

    def add(self, task: DownloadTask) -> None:
        """Insert a task or raise ``TaskRepositoryConflict`` for a duplicate ID."""
        ...

    def get(self, task_id: TaskId) -> DownloadTask | None: ...

    def replace(self, *, expected: DownloadTask, updated: DownloadTask) -> None:
        """Atomically replace an exact aggregate or raise ``TaskRepositoryConflict``."""
        ...

    def list_downloads(self) -> tuple[DownloadTask, ...]:
        """Return all tasks, newest first."""
        ...

    def list_history(self) -> tuple[DownloadTask, ...]:
        """Return terminal tasks, newest terminal attempt first."""
        ...


class SettingsStore(Protocol):
    def load(self) -> ApplicationSettings: ...

    def save(self, settings: ApplicationSettings) -> None: ...


class EventPublisher(Protocol):
    def publish(self, event: ApplicationEvent) -> None: ...


class Clock(Protocol):
    def now(self) -> UtcTimestamp: ...
