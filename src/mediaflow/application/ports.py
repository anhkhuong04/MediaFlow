"""Ports owned by the application core and implemented by adapters.

Analyzer, downloader, and processor calls may block. Their callers must schedule
them away from the presentation thread; these protocols deliberately contain no
Qt concepts.
"""

from typing import Protocol

from mediaflow.application.events import ApplicationEvent
from mediaflow.application.models import AnalysisOutcome, ApplicationSettings, DownloadArtifact
from mediaflow.domain import (
    DownloadRequest,
    DownloadTask,
    OutputPath,
    ProgressSnapshot,
    SourceUrl,
    TaskId,
    UtcTimestamp,
)


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
        request: DownloadRequest,
        *,
        progress: ProgressSink,
        cancellation: CancellationToken,
    ) -> DownloadArtifact: ...


class MediaProcessor(Protocol):
    def process(
        self,
        artifact: DownloadArtifact,
        request: DownloadRequest,
        *,
        progress: ProgressSink,
        cancellation: CancellationToken,
    ) -> OutputPath: ...


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
