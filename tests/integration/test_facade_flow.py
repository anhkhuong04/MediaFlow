from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock

from mediaflow.application import (
    AnalysisOutcome,
    AnalyzeUrl,
    ApplicationFacade,
    ApplicationSettings,
    CancelDownload,
    DependencyComponent,
    DependencyInfo,
    DependencyReport,
    DependencyState,
    DownloadArtifact,
    DownloadManager,
    EnqueueDownload,
    InProcessEventBus,
    PrepareProcessingRetry,
    PrepareResume,
    ProcessingManager,
    QueueManager,
    RestartDownload,
    RetryDownload,
)
from mediaflow.domain import (
    MediaInfo,
    MediaStream,
    OutputPath,
    SourceUrl,
    StreamKind,
    TaskState,
    UtcTimestamp,
    VideoPreset,
)
from tests.unit.application.fakes import (
    FakeAnalyzer,
    FakeDependencyProbe,
    FakeDownloader,
    FakeMediaProcessor,
    FakeRecoveryStore,
    InMemorySettingsStore,
    InMemoryTaskRepository,
)


@dataclass(frozen=True, slots=True)
class ExistingOutputInspector:
    def exists(self, output_path: OutputPath) -> bool:
        return output_path.value.is_file()


class IncrementingClock:
    def __init__(self) -> None:
        self._lock = Lock()
        self._value = 0

    def now(self) -> UtcTimestamp:
        with self._lock:
            self._value += 1
            seconds = self._value
        return UtcTimestamp(datetime(2026, 9, 7, tzinfo=UTC) + timedelta(seconds=seconds))


def test_headless_client_runs_analyze_download_process_and_history(tmp_path: Path) -> None:
    repository = InMemoryTaskRepository()
    events = InProcessEventBus()
    clock = IncrementingClock()
    recovery = FakeRecoveryStore()
    artifact = DownloadArtifact((OutputPath((tmp_path / "input.webm").resolve()),), True)
    final_path = (tmp_path / "final.mp4").resolve()
    final_path.write_bytes(b"verified media")
    download_manager = DownloadManager(
        downloader=FakeDownloader(artifact),
        repository=repository,
        events=events,
        clock=clock,
    )
    processing_manager = ProcessingManager(
        processor=FakeMediaProcessor(OutputPath(final_path)),
        repository=repository,
        events=events,
        clock=clock,
    )
    queue = QueueManager(
        download_manager,
        concurrency=1,
        processing_manager=processing_manager,
    )
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="test-analysis")
    media = MediaInfo(
        SourceUrl("https://example.com/media"),
        "Media",
        "Example",
        (MediaStream("opaque", StreamKind.AUDIO_VIDEO, height_pixels=1080),),
    )
    settings = InMemorySettingsStore(
        ApplicationSettings(OutputPath(tmp_path.resolve()), VideoPreset(), 1)
    )
    dependencies = FakeDependencyProbe(
        DependencyReport(
            tuple(
                DependencyInfo(component, DependencyState.NOT_FOUND)
                for component in DependencyComponent
            )
        )
    )
    facade = ApplicationFacade(
        analyze_url=AnalyzeUrl(FakeAnalyzer(AnalysisOutcome.succeeded(media)), events, clock),
        enqueue_download=EnqueueDownload(repository, events, clock),
        cancel_download=CancelDownload(repository, events, clock),
        retry_download=RetryDownload(repository, events, clock),
        prepare_resume=PrepareResume(repository, recovery, events, clock),
        restart_download=RestartDownload(repository, events, clock),
        prepare_processing_retry=PrepareProcessingRetry(repository, recovery, events, clock),
        repository=repository,
        settings=settings,
        dependencies=dependencies,
        recovery_store=recovery,
        output_files=ExistingOutputInspector(),
        events=events,
        queue=queue,
        analysis_executor=executor,
    )
    try:
        analysis = facade.analyze(str(media.source_url)).result.result(timeout=5)
        assert analysis.value is not None
        queued = facade.enqueue(
            configuration_id=analysis.value.configuration_id,
            preset_id_value="video.1080p.mp4.auto",
            output_directory=str(tmp_path.resolve()),
        )
        assert queued.value is not None
        assert queue.wait_for_idle(timeout_seconds=5)

        downloads = facade.downloads()
        assert downloads.summary.completed == 1
        assert downloads.items[0].status.value == TaskState.COMPLETED.value
        assert downloads.items[0].actions.can_open_output
        history = facade.history()
        assert len(history) == 1
        assert history[0].task_id == queued.value.task_id
    finally:
        executor.shutdown(wait=True)
        queue.shutdown()
