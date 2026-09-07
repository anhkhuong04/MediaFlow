from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Lock
from threading import enumerate as enumerate_threads

from mediaflow.application import (
    AnalysisOutcome,
    AnalyzeUrl,
    ApplicationFacade,
    ApplicationSettings,
    CancelDownload,
    CancellationToken,
    DependencyComponent,
    DependencyInfo,
    DependencyReport,
    DependencyState,
    DownloadArtifact,
    DownloadJob,
    DownloadManager,
    DownloadOutcome,
    EnqueueDownload,
    InProcessEventBus,
    PrepareProcessingRetry,
    PrepareResume,
    ProcessingJob,
    ProcessingManager,
    ProcessingOutcome,
    ProgressSink,
    QueueManager,
    RestartDownload,
    RetryDownload,
    StartupRecovery,
)
from mediaflow.domain import (
    Failure,
    FailureCategory,
    MediaInfo,
    MediaStream,
    OutputPath,
    SourceUrl,
    StreamKind,
    TaskState,
    UtcTimestamp,
    VideoPreset,
)
from mediaflow.infrastructure.filesystem import LocalOutputFileInspector
from mediaflow.infrastructure.persistence import SQLiteTaskRepository
from tests.unit.application.fakes import (
    FakeAnalyzer,
    FakeDependencyProbe,
    FakeRecoveryStore,
    InMemorySettingsStore,
)


class IncrementingClock:
    def __init__(self) -> None:
        self._lock = Lock()
        self._value = 0

    def now(self) -> UtcTimestamp:
        with self._lock:
            self._value += 1
            seconds = self._value
        return UtcTimestamp(datetime(2026, 9, 7, tzinfo=UTC) + timedelta(seconds=seconds))


@dataclass(slots=True)
class SuccessfulDownloader:
    artifact: DownloadArtifact

    def download(
        self,
        job: DownloadJob,
        *,
        progress: ProgressSink,
        cancellation: CancellationToken,
    ) -> DownloadOutcome:
        del job, progress
        if cancellation.is_cancelled():
            return DownloadOutcome.failed(
                Failure(FailureCategory.CANCELLED, "download.cancelled", False)
            )
        return DownloadOutcome.succeeded(self.artifact)


@dataclass(slots=True)
class WritingProcessor:
    output_directory: Path
    failing_titles: frozenset[str] = frozenset()
    calls: list[str] = field(default_factory=list)

    def process(
        self,
        job: ProcessingJob,
        *,
        progress: ProgressSink,
        cancellation: CancellationToken,
    ) -> ProcessingOutcome:
        del progress
        self.calls.append(job.request.media_title)
        if cancellation.is_cancelled():
            return ProcessingOutcome.failed(
                Failure(FailureCategory.CANCELLED, "processing.cancelled", False)
            )
        if job.request.media_title in self.failing_titles:
            return ProcessingOutcome.failed(
                Failure(FailureCategory.PROCESSING, "processing.ffmpeg_failed", True)
            )
        output = (self.output_directory / f"{job.request.media_title}.mp4").resolve()
        output.write_bytes(b"verified fake media")
        return ProcessingOutcome.succeeded(OutputPath(output))


@dataclass(slots=True)
class MixedDownloader:
    artifact: DownloadArtifact
    active_started: Event = field(default_factory=Event)
    release_active: Event = field(default_factory=Event)
    calls: list[str] = field(default_factory=list)

    def download(
        self,
        job: DownloadJob,
        *,
        progress: ProgressSink,
        cancellation: CancellationToken,
    ) -> DownloadOutcome:
        del progress
        title = job.request.media_title
        self.calls.append(title)
        if title == "active-cancel":
            self.active_started.set()
            if not self.release_active.wait(timeout=5):
                raise TimeoutError("release gate was not opened")
        if cancellation.is_cancelled():
            return DownloadOutcome.failed(
                Failure(FailureCategory.CANCELLED, "download.cancelled", False)
            )
        if title == "download-failure":
            return DownloadOutcome.failed(
                Failure(FailureCategory.NETWORK, "download.network", True)
            )
        return DownloadOutcome.succeeded(self.artifact)


@dataclass(slots=True)
class FacadeHarness:
    facade: ApplicationFacade
    queue: QueueManager
    executor: ThreadPoolExecutor

    def close(self) -> None:
        self.executor.shutdown(wait=True, cancel_futures=True)
        self.queue.shutdown()


def test_analyze_queue_process_persist_and_reopen_through_ui_facade(tmp_path: Path) -> None:
    database = tmp_path / "mediaflow.db"
    output = (tmp_path / "downloads").resolve()
    output.mkdir()
    media = _media("E2E media")
    artifact = DownloadArtifact((OutputPath((tmp_path / "input.webm").resolve()),), True)

    first = _facade_harness(database, output, media, SuccessfulDownloader(artifact))
    try:
        analysis = first.facade.analyze(str(media.source_url)).result.result(timeout=5)
        assert analysis.value is not None
        queued = first.facade.enqueue(
            configuration_id=analysis.value.configuration_id,
            preset_id_value="video.1080p.mp4.auto",
            output_directory=str(output),
        )
        assert queued.value is not None
        task_id = queued.value.task_id
        assert first.queue.wait_for_idle(timeout_seconds=5)
        assert first.facade.downloads().summary.completed == 1
    finally:
        first.close()

    reopened = _facade_harness(database, output, media, SuccessfulDownloader(artifact))
    try:
        downloads = reopened.facade.downloads()
        history = reopened.facade.history()
        details = reopened.facade.task_details(task_id)
        assert downloads.summary.completed == 1
        assert downloads.items[0].actions.can_open_output
        assert len(history) == 1
        assert history[0].task_id == task_id
        assert details.value is not None
        assert details.value.item.status.value == TaskState.COMPLETED.value
        assert details.value.item.output_path is not None
        assert Path(details.value.item.output_path).read_bytes() == b"verified fake media"
    finally:
        reopened.close()

    database.unlink()
    assert not database.exists(), "SQLite must not retain a Windows file handle after reopen"


def test_mixed_queue_isolates_failure_cancel_and_processing_lanes(tmp_path: Path) -> None:
    database = tmp_path / "mixed.db"
    repository = SQLiteTaskRepository(database)
    events = InProcessEventBus()
    clock = IncrementingClock()
    artifact = DownloadArtifact((OutputPath((tmp_path / "input.webm").resolve()),), True)
    downloader = MixedDownloader(artifact)
    processor = WritingProcessor(tmp_path, frozenset({"processing-failure"}))
    queue = QueueManager(
        DownloadManager(downloader=downloader, repository=repository, events=events, clock=clock),
        concurrency=1,
        processing_manager=ProcessingManager(
            processor=processor, repository=repository, events=events, clock=clock
        ),
    )
    enqueue = EnqueueDownload(repository, events, clock)
    titles = (
        "active-cancel",
        "queued-cancel",
        "success",
        "download-failure",
        "processing-failure",
    )
    tasks = {
        title: enqueue.execute(
            media=_media(title), preset=VideoPreset(), output_directory=OutputPath(tmp_path)
        )
        for title in titles
    }

    queue.enqueue(tasks["active-cancel"].task_id)
    assert downloader.active_started.wait(timeout=5)
    queue.enqueue_many(tuple(tasks[title].task_id for title in titles[1:]))
    assert queue.cancel(tasks["queued-cancel"].task_id)
    assert queue.cancel(tasks["active-cancel"].task_id)
    downloader.release_active.set()
    assert queue.wait_for_idle(timeout_seconds=5)
    queue.shutdown()

    expected = {
        "active-cancel": TaskState.CANCELLED,
        "queued-cancel": TaskState.CANCELLED,
        "success": TaskState.COMPLETED,
        "download-failure": TaskState.FAILED,
        "processing-failure": TaskState.FAILED,
    }
    for title, state in expected.items():
        persisted = repository.get(tasks[title].task_id)
        assert persisted is not None
        assert persisted.state is state
    download_failure = repository.get(tasks["download-failure"].task_id)
    processing_failure = repository.get(tasks["processing-failure"].task_id)
    assert download_failure is not None and download_failure.current_attempt.failure is not None
    assert processing_failure is not None and processing_failure.current_attempt.failure is not None
    assert download_failure.current_attempt.failure.category is FailureCategory.NETWORK
    assert processing_failure.current_attempt.failure.category is FailureCategory.PROCESSING
    assert processor.calls == ["success", "processing-failure"]
    assert "queued-cancel" not in downloader.calls
    _assert_no_worker_threads()


def test_restart_mid_download_persists_interruption_and_new_attempt(tmp_path: Path) -> None:
    database = tmp_path / "restart.db"
    repository = SQLiteTaskRepository(database)
    events = InProcessEventBus()
    clock = IncrementingClock()
    artifact = DownloadArtifact((OutputPath((tmp_path / "input.webm").resolve()),), True)
    gated = MixedDownloader(artifact)
    task = EnqueueDownload(repository, events, clock).execute(
        media=_media("active-cancel"),
        preset=VideoPreset(),
        output_directory=OutputPath(tmp_path),
    )
    first_queue = QueueManager(
        DownloadManager(downloader=gated, repository=repository, events=events, clock=clock),
        concurrency=1,
    )
    first_queue.enqueue(task.task_id)
    assert gated.active_started.wait(timeout=5)

    report = first_queue.shutdown(timeout_seconds=0)
    assert not report.clean
    interrupted = repository.get(task.task_id)
    assert interrupted is not None
    assert interrupted.state is TaskState.INTERRUPTED
    gated.release_active.set()
    assert first_queue.wait_for_idle(timeout_seconds=5)

    reopened = SQLiteTaskRepository(database)
    assert StartupRecovery(reopened, events, clock).execute().recovered_task_ids == ()
    restarted = RestartDownload(reopened, events, clock).execute(task.task_id).task
    processor = WritingProcessor(tmp_path)
    second_queue = QueueManager(
        DownloadManager(
            downloader=SuccessfulDownloader(artifact),
            repository=reopened,
            events=events,
            clock=clock,
        ),
        concurrency=1,
        processing_manager=ProcessingManager(
            processor=processor, repository=reopened, events=events, clock=clock
        ),
    )
    second_queue.enqueue(restarted.task_id)
    assert second_queue.wait_for_idle(timeout_seconds=5)
    second_queue.shutdown()

    persisted = SQLiteTaskRepository(database).get(task.task_id)
    assert persisted is not None
    assert persisted.state is TaskState.COMPLETED
    assert len(persisted.attempts) == 2
    assert persisted.attempts[0].failure is not None
    assert persisted.attempts[0].failure.code == "recovery.full_restart"
    _assert_no_worker_threads()


def _facade_harness(
    database: Path,
    output: Path,
    media: MediaInfo,
    downloader: SuccessfulDownloader,
) -> FacadeHarness:
    repository = SQLiteTaskRepository(database)
    events = InProcessEventBus()
    clock = IncrementingClock()
    recovery = FakeRecoveryStore()
    queue = QueueManager(
        DownloadManager(downloader=downloader, repository=repository, events=events, clock=clock),
        concurrency=1,
        processing_manager=ProcessingManager(
            processor=WritingProcessor(output),
            repository=repository,
            events=events,
            clock=clock,
        ),
    )
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="test-analysis")
    settings = InMemorySettingsStore(ApplicationSettings(OutputPath(output), VideoPreset(), 1))
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
        output_files=LocalOutputFileInspector(),
        events=events,
        queue=queue,
        analysis_executor=executor,
    )
    return FacadeHarness(facade, queue, executor)


def _media(title: str) -> MediaInfo:
    return MediaInfo(
        SourceUrl(f"https://example.com/{title}"),
        title,
        "Release gate fixture",
        (MediaStream("opaque", StreamKind.AUDIO_VIDEO, height_pixels=1080),),
    )


def _assert_no_worker_threads() -> None:
    assert not any(
        thread.is_alive() and thread.name.startswith(("mediaflow-download", "mediaflow-analysis"))
        for thread in enumerate_threads()
    )
