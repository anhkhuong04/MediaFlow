"""The single composition root for concrete MediaFlow runtime adapters."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from mediaflow.application import (
    AnalyzeUrl,
    ApplicationFacade,
    ApplicationSettings,
    CancelDownload,
    DownloadManager,
    EnqueueDownload,
    InProcessEventBus,
    PrepareProcessingRetry,
    PrepareResume,
    ProcessingManager,
    QueueManager,
    RestartDownload,
    RetryDownload,
    ShutdownCoordinator,
    ShutdownReport,
    StartupRecovery,
)
from mediaflow.domain import OutputPath, TaskState, UtcTimestamp, VideoPreset
from mediaflow.infrastructure.downloader import YtDlpAnalyzer, YtDlpDownloader
from mediaflow.infrastructure.filesystem.output_inspector import LocalOutputFileInspector
from mediaflow.infrastructure.filesystem.staging_recovery import StagingRecoveryStore
from mediaflow.infrastructure.media import (
    FfmpegMediaProcessor,
    MediaDependencyProbe,
    SubprocessRunner,
)
from mediaflow.infrastructure.persistence import SQLiteTaskRepository
from mediaflow.infrastructure.settings import JsonSettingsStore
from mediaflow.logging_setup import configure_logging, shutdown_logging


@dataclass(frozen=True, slots=True)
class BootstrapConfig:
    data_directory: Path
    default_output_directory: Path
    shutdown_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.data_directory.is_absolute() or not self.default_output_directory.is_absolute():
            raise ValueError("Bootstrap directories must be absolute")
        if self.shutdown_timeout_seconds < 0:
            raise ValueError("Shutdown timeout cannot be negative")


@dataclass(slots=True)
class MediaFlowRuntime:
    facade: ApplicationFacade
    shutdown_coordinator: ShutdownCoordinator
    analysis_executor: ThreadPoolExecutor
    logs_directory: Path
    _closed: bool = False

    def shutdown(self) -> ShutdownReport:
        if self._closed:
            raise RuntimeError("MediaFlow runtime is already closed")
        self._closed = True
        self.facade.cancel_all_analyses()
        self.analysis_executor.shutdown(wait=True, cancel_futures=True)
        report = self.shutdown_coordinator.execute()
        shutdown_logging()
        return report

    def __enter__(self) -> "MediaFlowRuntime":
        return self

    def __exit__(self, *exception: object) -> None:
        self.shutdown()


def build_runtime(config: BootstrapConfig) -> MediaFlowRuntime:
    """Construct every concrete adapter without importing presentation code."""

    logs_directory = config.data_directory / "logs"
    configure_logging(logs_directory)
    defaults = ApplicationSettings(
        default_output_directory=OutputPath(config.default_output_directory),
        default_preset=VideoPreset(),
        concurrent_downloads=2,
    )
    settings = JsonSettingsStore(config.data_directory / "settings.json", defaults)
    current_settings = settings.load()
    repository = SQLiteTaskRepository(config.data_directory / "mediaflow.db")
    events = InProcessEventBus()
    clock = _SystemClock()
    recovery_store = StagingRecoveryStore()
    output_files = LocalOutputFileInspector()
    runner = SubprocessRunner()
    dependencies = MediaDependencyProbe(runner)
    download_manager = DownloadManager(
        downloader=YtDlpDownloader(),
        repository=repository,
        events=events,
        clock=clock,
    )
    processing_manager = ProcessingManager(
        processor=FfmpegMediaProcessor(runner),
        repository=repository,
        events=events,
        clock=clock,
    )
    queue = QueueManager(
        download_manager,
        concurrency=current_settings.concurrent_downloads,
        processing_manager=processing_manager,
    )
    analysis_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mediaflow-analysis")
    StartupRecovery(repository, events, clock).execute()
    queue.enqueue_many(
        tuple(
            task.task_id for task in repository.list_downloads() if task.state is TaskState.QUEUED
        )
    )
    facade = ApplicationFacade(
        analyze_url=AnalyzeUrl(YtDlpAnalyzer(), events, clock),
        enqueue_download=EnqueueDownload(repository, events, clock),
        cancel_download=CancelDownload(repository, events, clock),
        retry_download=RetryDownload(repository, events, clock),
        prepare_resume=PrepareResume(repository, recovery_store, events, clock),
        restart_download=RestartDownload(repository, events, clock),
        prepare_processing_retry=PrepareProcessingRetry(repository, recovery_store, events, clock),
        repository=repository,
        settings=settings,
        dependencies=dependencies,
        recovery_store=recovery_store,
        output_files=output_files,
        events=events,
        queue=queue,
        analysis_executor=analysis_executor,
    )
    return MediaFlowRuntime(
        facade,
        ShutdownCoordinator(queue, config.shutdown_timeout_seconds),
        analysis_executor,
        logs_directory,
    )


@dataclass(frozen=True, slots=True)
class _SystemClock:
    def now(self) -> UtcTimestamp:
        return UtcTimestamp.now()
