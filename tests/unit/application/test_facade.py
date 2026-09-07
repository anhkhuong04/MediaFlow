from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import current_thread
from typing import Any, get_args, get_origin, get_type_hints

from mediaflow.application import (
    AnalysisOutcome,
    AnalyzeUrl,
    ApplicationEvent,
    ApplicationFacade,
    ApplicationSettings,
    CancelDownload,
    DependencyComponent,
    DependencyInfo,
    DependencyReport,
    DependencyState,
    DownloadArtifact,
    DownloadItemView,
    EnqueueDownload,
    InProcessEventBus,
    MediaConfigurationView,
    PrepareProcessingRetry,
    PrepareResume,
    RestartDownload,
    RetryDownload,
    SuggestedAction,
    TaskQueued,
)
from mediaflow.application.ports import CancellationToken
from mediaflow.domain import (
    Failure,
    FailureCategory,
    MediaInfo,
    MediaStream,
    OutputPath,
    SourceUrl,
    StreamKind,
    TaskId,
    UtcTimestamp,
    VideoPreset,
)
from tests.unit.application.fakes import (
    FakeClock,
    FakeDependencyProbe,
    FakeRecoveryStore,
    InMemorySettingsStore,
    InMemoryTaskRepository,
)


@dataclass(slots=True)
class RecordingAnalyzer:
    outcome: AnalysisOutcome
    thread_names: list[str] = field(default_factory=list)

    def analyze(self, source_url: SourceUrl, *, cancellation: CancellationToken) -> AnalysisOutcome:
        del source_url, cancellation
        self.thread_names.append(current_thread().name)
        return self.outcome


@dataclass(slots=True)
class FakeScheduler:
    queued: list[TaskId] = field(default_factory=list)
    processing: list[tuple[TaskId, DownloadArtifact]] = field(default_factory=list)
    cancelled: list[TaskId] = field(default_factory=list)

    def enqueue(self, task_id: TaskId) -> None:
        self.queued.append(task_id)

    def enqueue_processing(self, task_id: TaskId, artifact: DownloadArtifact) -> None:
        self.processing.append((task_id, artifact))

    def cancel(self, task_id: TaskId) -> bool:
        self.cancelled.append(task_id)
        return True


@dataclass(frozen=True, slots=True)
class FakeOutputInspector:
    def exists(self, output_path: OutputPath) -> bool:
        return output_path.value.is_file()


def test_facade_runs_analysis_off_caller_thread_and_queues_by_opaque_preset_id(
    tmp_path: Path,
) -> None:
    analyzer = RecordingAnalyzer(AnalysisOutcome.succeeded(_media()))
    facade, executor, scheduler, repository, events = _facade(tmp_path, analyzer)
    observed: list[ApplicationEvent] = []
    subscription = facade.subscribe(observed.append)
    try:
        request = facade.analyze("https://example.com/media")
        analyzed = request.result.result(timeout=5)
        assert isinstance(analyzed.value, MediaConfigurationView)
        assert analyzer.thread_names[0].startswith("test-analysis")
        assert analyzer.thread_names[0] != current_thread().name
        configuration = analyzed.value
        preset = next(
            option for option in configuration.presets if option.preset_id == "video.1080p.mp4.auto"
        )
        assert preset.available

        queued = facade.enqueue(
            configuration_id=configuration.configuration_id,
            preset_id_value=preset.preset_id,
            output_directory=str(tmp_path.resolve()),
        )
        assert isinstance(queued.value, DownloadItemView)
        assert queued.value.actions.can_cancel
        assert scheduler.queued == [TaskId.parse(queued.value.task_id)]
        assert facade.downloads().summary.queued == 1
        assert facade.task_details(queued.value.task_id).value is not None
        assert repository.list_history() == ()
        assert any(isinstance(event, TaskQueued) for event in observed)
    finally:
        subscription.close()
        executor.shutdown(wait=True)


def test_facade_returns_safe_errors_and_settings_dependency_views(tmp_path: Path) -> None:
    failure = Failure(FailureCategory.NETWORK, "analysis.network", retryable=True)
    facade, executor, _, _, _ = _facade(
        tmp_path, RecordingAnalyzer(AnalysisOutcome.failed(failure))
    )
    try:
        invalid = facade.analyze("not a url").result.result(timeout=1)
        assert invalid.error is not None
        assert invalid.error.technical_code == "error.invalid_url"
        assert "not a url" not in repr(invalid.error)

        failed = facade.analyze("https://example.com/media").result.result(timeout=5)
        assert failed.error is not None
        assert failed.error.technical_code == "analysis.network"
        assert failed.error.suggested_action is SuggestedAction.RETRY

        settings = facade.load_settings()
        saved = facade.save_settings(
            default_output_directory=str(tmp_path.resolve()),
            default_preset_id=settings.default_preset_id,
            concurrent_downloads=3,
        )
        assert saved.value is not None
        assert saved.value.concurrent_downloads == 3
        dependencies = facade.dependency_status()
        assert {item.component for item in dependencies} == {
            component.value for component in DependencyComponent
        }
        assert all(item.state == "not_found" for item in dependencies)
    finally:
        executor.shutdown(wait=True)


def test_facade_contract_dataclasses_contain_no_raw_or_third_party_types() -> None:
    from mediaflow.application import (
        AttemptView,
        DependencyStatusView,
        DownloadSummaryView,
        DownloadsView,
        HistoryItemView,
        PresetOptionView,
        ProgressView,
        SettingsView,
        TaskActionsView,
        TaskDetailsView,
        UserMessage,
    )

    view_types = (
        AttemptView,
        DependencyStatusView,
        DownloadItemView,
        DownloadSummaryView,
        DownloadsView,
        HistoryItemView,
        MediaConfigurationView,
        PresetOptionView,
        ProgressView,
        SettingsView,
        TaskActionsView,
        TaskDetailsView,
        UserMessage,
    )
    for view_type in view_types:
        assert is_dataclass(view_type)
        assert fields(view_type)
        for annotation in get_type_hints(view_type).values():
            assert not _contains_raw_or_third_party(annotation)


def _facade(
    tmp_path: Path, analyzer: RecordingAnalyzer
) -> tuple[
    ApplicationFacade,
    ThreadPoolExecutor,
    FakeScheduler,
    InMemoryTaskRepository,
    InProcessEventBus,
]:
    repository = InMemoryTaskRepository()
    events = InProcessEventBus()
    scheduler = FakeScheduler()
    recovery_store = FakeRecoveryStore()
    clock = FakeClock([_at(index) for index in range(30)])
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="test-analysis")
    settings = InMemorySettingsStore(
        ApplicationSettings(OutputPath(tmp_path.resolve()), VideoPreset(), 2)
    )
    report = DependencyReport(
        tuple(
            DependencyInfo(component, DependencyState.NOT_FOUND)
            for component in DependencyComponent
        )
    )
    facade = ApplicationFacade(
        analyze_url=AnalyzeUrl(analyzer, events, clock),
        enqueue_download=EnqueueDownload(repository, events, clock),
        cancel_download=CancelDownload(repository, events, clock),
        retry_download=RetryDownload(repository, events, clock),
        prepare_resume=PrepareResume(repository, recovery_store, events, clock),
        restart_download=RestartDownload(repository, events, clock),
        prepare_processing_retry=PrepareProcessingRetry(repository, recovery_store, events, clock),
        repository=repository,
        settings=settings,
        dependencies=FakeDependencyProbe(report),
        recovery_store=recovery_store,
        output_files=FakeOutputInspector(),
        events=events,
        queue=scheduler,
        analysis_executor=executor,
    )
    return facade, executor, scheduler, repository, events


def _media() -> MediaInfo:
    return MediaInfo(
        source_url=SourceUrl("https://example.com/media"),
        title="Media",
        source_name="Example",
        streams=(
            MediaStream(
                key="opaque",
                kind=StreamKind.AUDIO_VIDEO,
                height_pixels=1080,
            ),
        ),
    )


def _at(seconds: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 9, 7, tzinfo=UTC) + timedelta(seconds=seconds))


def _contains_raw_or_third_party(annotation: object) -> bool:
    origin = get_origin(annotation)
    if annotation in {Any, dict} or origin is dict:
        return True
    module = getattr(annotation, "__module__", "")
    if module.startswith(("yt_dlp", "sqlite3", "subprocess", "PySide6")):
        return True
    return any(_contains_raw_or_third_party(argument) for argument in get_args(annotation))
