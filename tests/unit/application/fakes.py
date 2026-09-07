from dataclasses import dataclass, field

from mediaflow.application import (
    AnalysisOutcome,
    ApplicationEvent,
    ApplicationSettings,
    CancellationToken,
    CleanupDisposition,
    DependencyReport,
    DownloadArtifact,
    DownloadJob,
    DownloadOutcome,
    ProcessingJob,
    ProcessingOutcome,
    ProgressSink,
    TaskRepositoryConflict,
)
from mediaflow.domain import (
    TERMINAL_STATES,
    DownloadTask,
    OutputPath,
    ProgressSnapshot,
    SourceUrl,
    TaskId,
    UtcTimestamp,
)


@dataclass(slots=True)
class FakeClock:
    values: list[UtcTimestamp]

    def now(self) -> UtcTimestamp:
        if not self.values:
            raise AssertionError("Fake clock has no timestamp remaining")
        return self.values.pop(0)


@dataclass(slots=True)
class FakeCancellationToken:
    values: list[bool] = field(default_factory=lambda: [False])

    def __post_init__(self) -> None:
        self.values = list(self.values)

    def is_cancelled(self) -> bool:
        if len(self.values) > 1:
            return self.values.pop(0)
        return self.values[0]


@dataclass(slots=True)
class FakeAnalyzer:
    outcome: AnalysisOutcome
    calls: list[SourceUrl] = field(default_factory=list)

    def analyze(self, source_url: SourceUrl, *, cancellation: CancellationToken) -> AnalysisOutcome:
        self.calls.append(source_url)
        return self.outcome


@dataclass(slots=True)
class CollectingEventPublisher:
    events: list[ApplicationEvent] = field(default_factory=list)
    operation_log: list[str] | None = None
    fail: bool = False

    def publish(self, event: ApplicationEvent) -> None:
        if self.operation_log is not None:
            self.operation_log.append("event.publish")
        if self.fail:
            raise RuntimeError("simulated event delivery failure")
        self.events.append(event)


@dataclass(slots=True)
class InMemoryTaskRepository:
    tasks: dict[TaskId, DownloadTask] = field(default_factory=dict)
    operation_log: list[str] | None = None

    def add(self, task: DownloadTask) -> None:
        if self.operation_log is not None:
            self.operation_log.append("repository.add")
        if task.task_id in self.tasks:
            raise TaskRepositoryConflict("task already exists")
        self.tasks[task.task_id] = task

    def get(self, task_id: TaskId) -> DownloadTask | None:
        return self.tasks.get(task_id)

    def replace(self, *, expected: DownloadTask, updated: DownloadTask) -> None:
        if self.operation_log is not None:
            self.operation_log.append("repository.replace")
        current = self.tasks.get(expected.task_id)
        if current != expected or updated.task_id != expected.task_id:
            raise TaskRepositoryConflict("optimistic repository conflict")
        self.tasks[updated.task_id] = updated

    def list_downloads(self) -> tuple[DownloadTask, ...]:
        return tuple(sorted(self.tasks.values(), key=lambda task: task.created_at, reverse=True))

    def list_history(self) -> tuple[DownloadTask, ...]:
        terminal = [task for task in self.tasks.values() if task.state in TERMINAL_STATES]
        return tuple(
            sorted(
                terminal,
                key=lambda task: task.current_attempt.finished_at or task.created_at,
                reverse=True,
            )
        )


@dataclass(slots=True)
class FakeProgressSink:
    values: list[ProgressSnapshot] = field(default_factory=list)

    def report(self, progress: ProgressSnapshot) -> None:
        self.values.append(progress)


@dataclass(slots=True)
class FakeDownloader:
    result: DownloadArtifact

    def download(
        self,
        job: DownloadJob,
        *,
        progress: ProgressSink,
        cancellation: CancellationToken,
    ) -> DownloadOutcome:
        del job, progress, cancellation
        return DownloadOutcome.succeeded(self.result)


@dataclass(slots=True)
class FakeMediaProcessor:
    result: OutputPath

    def process(
        self,
        job: ProcessingJob,
        *,
        progress: ProgressSink,
        cancellation: CancellationToken,
    ) -> ProcessingOutcome:
        del job, progress, cancellation
        return ProcessingOutcome.succeeded(self.result)


@dataclass(slots=True)
class FakeDependencyProbe:
    report: DependencyReport

    def probe(self) -> DependencyReport:
        return self.report


@dataclass(slots=True)
class FakeRecoveryStore:
    partial: bool = False
    artifact: DownloadArtifact | None = None
    cleanup_calls: list[tuple[DownloadTask, CleanupDisposition]] = field(default_factory=list)

    def has_resumable_partial(self, task: DownloadTask) -> bool:
        del task
        return self.partial

    def load_processing_artifact(self, task: DownloadTask) -> DownloadArtifact | None:
        del task
        return self.artifact

    def cleanup(self, task: DownloadTask, disposition: CleanupDisposition) -> None:
        self.cleanup_calls.append((task, disposition))


@dataclass(slots=True)
class InMemorySettingsStore:
    settings: ApplicationSettings

    def load(self) -> ApplicationSettings:
        return self.settings

    def save(self, settings: ApplicationSettings) -> None:
        self.settings = settings
