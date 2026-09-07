from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import QWidget

from mediaflow.application import (
    AnalysisFailed,
    AnalysisRequest,
    ApplicationEvent,
    CommandResult,
    DependencyStatusView,
    DownloadItemView,
    DownloadStatus,
    DownloadSummaryView,
    DownloadsView,
    EventSubscription,
    HistoryItemView,
    HistoryRemovalView,
    InProcessEventBus,
    MediaConfigurationView,
    MediaKind,
    PresetOptionView,
    ProgressView,
    SettingsView,
    TaskActionsView,
    TaskDetailsView,
    TaskProgressChanged,
    TaskStateChanged,
)
from mediaflow.application.messages import command_message
from mediaflow.domain import (
    AttemptId,
    Failure,
    FailureCategory,
    ProgressSnapshot,
    SourceUrl,
    TaskId,
    TaskState,
    UtcTimestamp,
)
from mediaflow.presentation.bridge import PresentationCommandRunner, QtEventBridge
from mediaflow.presentation.controllers import (
    DownloadsController,
    HistoryController,
    HomeController,
    SettingsController,
    TaskAction,
)
from mediaflow.presentation.coordinator import PresentationCoordinator
from mediaflow.presentation.downloads import DownloadsPage
from mediaflow.presentation.history import HistoryPage
from mediaflow.presentation.home import HomePage
from mediaflow.presentation.settings import SettingsPage
from mediaflow.presentation.window import MediaFlowWindow


def test_bridge_marshals_worker_events_to_ui_thread_and_stops_after_close(qtbot: object) -> None:
    facade = FakePresentationFacade()
    bridge = QtEventBridge(facade, progress_interval_ms=1)
    bridge.start()
    bridge.start()
    delivered: list[ApplicationEvent] = []
    delivery_threads: list[QThread] = []

    def receive(event: ApplicationEvent) -> None:
        delivered.append(event)
        delivery_threads.append(QThread.currentThread())

    bridge.application_event.connect(receive)
    event = AnalysisFailed(
        SourceUrl("https://example.com/media"),
        Failure(FailureCategory.NETWORK, "analysis.network", True),
        _at(1),
    )

    worker = Thread(target=facade.events.publish, args=(event,), name="bridge-event-worker")
    worker.start()
    worker.join(timeout=5)
    assert not worker.is_alive()
    _wait_until(qtbot, lambda: delivered == [event])

    assert delivery_threads == [QThread.currentThread()]
    bridge.close()
    facade.events.publish(event)
    _wait(qtbot, 10)
    assert delivered == [event]


def test_progress_burst_is_coalesced_but_state_event_flushes_latest_snapshot(qtbot: object) -> None:
    facade = FakePresentationFacade()
    bridge = QtEventBridge(facade, progress_interval_ms=1_000)
    bridge.start()
    received: list[ApplicationEvent] = []
    bridge.application_event.connect(received.append)
    task_id = TaskId.new()
    attempt_id = AttemptId.new()
    first = _progress_event(task_id, attempt_id, 10, 100, 1)
    latest = _progress_event(task_id, attempt_id, 80, 100, 2)
    state = TaskStateChanged(task_id, attempt_id, TaskState.QUEUED, TaskState.DOWNLOADING, _at(3))

    facade.events.publish(first)
    facade.events.publish(latest)
    facade.events.publish(state)

    _wait_until(qtbot, lambda: received == [latest, state])
    bridge.close()


def test_window_close_releases_presentation_subscription(qtbot: object) -> None:
    facade = FakePresentationFacade()
    coordinator = PresentationCoordinator(facade)
    coordinator.start()
    received: list[ApplicationEvent] = []
    coordinator.bridge.application_event.connect(received.append)
    window = MediaFlowWindow()
    window.closed.connect(coordinator.close)
    _add_widget(qtbot, window)
    window.close()

    facade.events.publish(
        AnalysisFailed(
            SourceUrl("https://example.com/media"),
            Failure(FailureCategory.NETWORK, "analysis.network", True),
            _at(1),
        )
    )
    _wait(qtbot, 10)
    assert coordinator.is_closed
    assert received == []


def test_download_controller_updates_one_stable_task_row_and_preserves_selection(
    qtbot: object,
) -> None:
    first_id = TaskId.new()
    second_id = TaskId.new()
    facade = FakePresentationFacade(
        items={
            str(first_id): _item(first_id, "First", 0.1),
            str(second_id): _item(second_id, "Second", None),
        }
    )
    bridge = QtEventBridge(facade, progress_interval_ms=1)
    runner = PresentationCommandRunner(bridge)
    controller = DownloadsController(facade, runner)
    bridge.command_completed.connect(controller.handle_completion)
    bridge.application_event.connect(controller.handle_event)
    bridge.start()
    controller.refresh()
    _wait_until(qtbot, lambda: len(controller.state.items) == 2)
    controller.select_task(str(second_id))
    unchanged_second = next(
        item for item in controller.state.items if item.task_id == str(second_id)
    )

    facade.items[str(first_id)] = _item(first_id, "First updated", 0.8)
    facade.events.publish(_progress_event(first_id, AttemptId.new(), 80, 100, 4))

    _wait_until(
        qtbot,
        lambda: (
            next(item for item in controller.state.items if item.task_id == str(first_id)).title
            == "First updated"
        ),
    )
    updated_second = next(item for item in controller.state.items if item.task_id == str(second_id))
    assert controller.state.selected_task_id == str(second_id)
    assert updated_second is unchanged_second
    assert updated_second.progress is None

    bridge.close()
    runner.close()


def test_analyze_and_task_action_reject_duplicate_intent_until_completion(qtbot: object) -> None:
    task_id = TaskId.new()
    facade = FakePresentationFacade(items={str(task_id): _item(task_id, "Task", None)})
    bridge = QtEventBridge(facade)
    runner = PresentationCommandRunner(bridge)
    home = HomeController(facade, bridge, runner)
    downloads = DownloadsController(facade, runner)
    bridge.command_completed.connect(home.handle_completion)
    bridge.command_completed.connect(downloads.handle_completion)

    assert home.analyze("https://example.com/media")
    assert not home.analyze("https://example.com/other")
    facade.analysis_result.set_result(CommandResult.succeeded(_configuration()))
    _wait_until(qtbot, lambda: not home.state.analysis.is_busy)
    assert home.state.configuration is not None

    facade.action_started.clear()
    facade.allow_action.clear()
    assert home.enqueue(preset_id="video.1080p.mp4.auto", output_directory="C:\\")
    _wait_until(qtbot, facade.action_started.is_set)
    assert not home.enqueue(preset_id="video.1080p.mp4.auto", output_directory="C:\\")
    facade.allow_action.set()
    _wait_until(qtbot, lambda: not home.state.enqueue.is_busy)

    facade.action_started.clear()
    facade.allow_action.clear()
    assert downloads.invoke_action(str(task_id), TaskAction.RESUME)
    _wait_until(qtbot, facade.action_started.is_set)
    assert not downloads.invoke_action(str(task_id), TaskAction.RESUME)
    facade.allow_action.set()
    _wait_until(
        qtbot,
        lambda: (
            not any(
                state.task_id == str(task_id)
                and state.action is TaskAction.RESUME
                and state.state.is_busy
                for state in downloads.state.action_states
            )
        ),
    )

    bridge.close()
    runner.close()


def test_home_page_keeps_url_explicit_and_exposes_only_normalized_preset_choices(
    qtbot: object,
) -> None:
    facade = FakePresentationFacade()
    bridge = QtEventBridge(facade)
    runner = PresentationCommandRunner(bridge)
    home = HomeController(facade, bridge, runner)
    page = HomePage(home)
    bridge.command_completed.connect(home.handle_completion)
    bridge.start()
    _add_widget(qtbot, page)
    page.show()

    page.url_input.setText("https://example.com/media")
    assert not home.state.analysis.is_busy
    page.analyze_button.click()
    assert home.state.analysis.is_busy
    assert page.cancel_button.isVisible()
    assert page.configuration_card.isHidden()

    facade.analysis_result.set_result(CommandResult.succeeded(_configuration_with_presets()))
    _wait_until(qtbot, lambda: home.state.configuration is not None)
    assert page.url_input.text() == "https://example.com/media"
    assert page.configuration_card.isVisible()
    assert page.preset_combo.currentData(Qt.ItemDataRole.UserRole) == "video.1080p.mp4.auto"
    assert not page.add_button.isEnabled()

    page.set_default_output_directory("C:\\Downloads")
    assert page.add_button.isEnabled()
    page.audio_button.click()
    assert page.conversion_notice.isVisible()
    assert page.preset_combo.currentData(Qt.ItemDataRole.UserRole) == "audio.best.mp3.auto"

    bridge.close()
    runner.close()


def test_downloads_page_updates_the_existing_card_for_one_task_event(qtbot: object) -> None:
    task_id = TaskId.new()
    facade = FakePresentationFacade(items={str(task_id): _item(task_id, "Task", 0.4)})
    bridge = QtEventBridge(facade, progress_interval_ms=1)
    runner = PresentationCommandRunner(bridge)
    controller = DownloadsController(facade, runner)
    page = DownloadsPage(controller)
    bridge.command_completed.connect(controller.handle_completion)
    bridge.application_event.connect(controller.handle_event)
    bridge.start()
    _add_widget(qtbot, page)
    page.show()
    controller.refresh()
    _wait_until(qtbot, lambda: str(task_id) in page._cards)
    original_card = page._cards[str(task_id)]

    facade.items[str(task_id)] = _item(task_id, "Task", None, status=DownloadStatus.PROCESSING)
    facade.events.publish(_progress_event(task_id, AttemptId.new(), 80, 100, 4))
    _wait_until(qtbot, lambda: page._cards[str(task_id)]._item.status is DownloadStatus.PROCESSING)

    assert page._cards[str(task_id)] is original_card
    assert original_card.progress.maximum() == 0
    assert original_card.open_file.isHidden()
    bridge.close()
    runner.close()


def test_history_page_fetches_source_only_after_an_explicit_user_action(qtbot: object) -> None:
    task_id = TaskId.new()
    active_item = _item(task_id, "Saved media", None, status=DownloadStatus.COMPLETED)
    facade = FakePresentationFacade(
        items={str(task_id): active_item}, history_items=(_history_item(active_item),)
    )
    bridge = QtEventBridge(facade)
    runner = PresentationCommandRunner(bridge)
    controller = HistoryController(facade, runner)
    page = HistoryPage(controller)
    bridge.command_completed.connect(controller.handle_completion)
    bridge.start()
    _add_widget(qtbot, page)
    page.show()
    controller.refresh()
    _wait_until(qtbot, lambda: str(task_id) in page._cards)
    requested: list[str] = []
    page.download_again_requested.connect(requested.append)

    page._cards[str(task_id)].download_button.click()

    _wait_until(qtbot, lambda: requested == ["https://example.com/media"])
    bridge.close()
    runner.close()


def test_settings_page_saves_typed_preferences_without_touching_real_user_settings(
    qtbot: object,
) -> None:
    facade = FakePresentationFacade()
    bridge = QtEventBridge(facade)
    runner = PresentationCommandRunner(bridge)
    controller = SettingsController(facade, runner)
    page = SettingsPage(controller)
    bridge.command_completed.connect(controller.handle_completion)
    bridge.start()
    _add_widget(qtbot, page)
    page.show()
    controller.load()
    controller.load_dependencies()
    _wait_until(qtbot, lambda: page._loaded is not None)

    page.folder.setText("C:\\Media")
    page.theme.setCurrentIndex(page.theme.findData("dark"))
    page.audio_output.setCurrentIndex(page.audio_output.findData("mp3"))
    page.concurrency.setValue(4)
    page.save_button.click()

    _wait_until(qtbot, lambda: not controller.state.save.is_busy)
    assert controller.state.settings is not None
    assert controller.state.settings.default_output_directory == "C:\\Media"
    assert controller.state.settings.default_audio_preset_id == "audio.best.mp3.auto"
    assert controller.state.settings.theme == "dark"
    assert controller.state.settings.concurrent_downloads == 4
    assert not page._dirty
    bridge.close()
    runner.close()


def test_settings_page_emits_one_non_blocking_first_run_prompt_for_missing_ffmpeg(
    qtbot: object,
) -> None:
    dependency = DependencyStatusView("ffmpeg", "not_found", None, "dependency.ffmpeg.unavailable")
    facade = FakePresentationFacade(dependencies=(dependency,))
    bridge = QtEventBridge(facade)
    runner = PresentationCommandRunner(bridge)
    controller = SettingsController(facade, runner)
    page = SettingsPage(controller)
    bridge.command_completed.connect(controller.handle_completion)
    bridge.start()
    _add_widget(qtbot, page)
    prompted: list[tuple[DependencyStatusView, ...]] = []
    page.first_run_ready.connect(prompted.append)

    controller.load()
    controller.load_dependencies()
    _wait_until(qtbot, lambda: prompted == [(dependency,)])
    controller.load_dependencies()
    _wait(qtbot, 20)

    assert prompted == [(dependency,)]
    bridge.close()
    runner.close()


def test_presentation_layer_does_not_depend_on_infrastructure_modules() -> None:
    presentation_root = Path(__file__).parents[2] / "src" / "mediaflow" / "presentation"

    assert all(
        "mediaflow.infrastructure" not in source.read_text(encoding="utf-8")
        for source in presentation_root.glob("*.py")
    )


class FakePresentationFacade:
    """Deterministic C8-shaped fake; it contains no infrastructure adapter behavior."""

    def __init__(
        self,
        *,
        items: dict[str, DownloadItemView] | None = None,
        history_items: tuple[HistoryItemView, ...] = (),
        dependencies: tuple[DependencyStatusView, ...] = (),
    ) -> None:
        self.events = InProcessEventBus()
        self.items = dict(items or {})
        self.history_items = history_items
        self.dependencies = dependencies
        self.analysis_result: Future[CommandResult[MediaConfigurationView]] = Future()
        self.action_started = Event()
        self.allow_action = Event()

    def subscribe(self, subscriber: Callable[[ApplicationEvent], None]) -> EventSubscription:
        return self.events.subscribe(subscriber)

    def analyze(self, source_url: str) -> AnalysisRequest:
        del source_url
        return AnalysisRequest("analysis-request", self.analysis_result)

    def cancel_analysis(self, request_id: str) -> bool:
        del request_id
        return True

    def enqueue(
        self, *, configuration_id: str, preset_id_value: str, output_directory: str
    ) -> CommandResult[DownloadItemView]:
        del configuration_id, preset_id_value, output_directory
        return self._action_result(next(iter(self.items)))

    def cancel(self, task_id: str) -> CommandResult[DownloadItemView]:
        return self._action_result(task_id)

    def retry(self, task_id: str) -> CommandResult[DownloadItemView]:
        return self._action_result(task_id)

    def resume(self, task_id: str) -> CommandResult[DownloadItemView]:
        return self._action_result(task_id)

    def restart(self, task_id: str) -> CommandResult[DownloadItemView]:
        return self._action_result(task_id)

    def retry_processing(self, task_id: str) -> CommandResult[DownloadItemView]:
        return self._action_result(task_id)

    def downloads(self) -> DownloadsView:
        items = tuple(self.items.values())
        return DownloadsView(DownloadSummaryView(0, len(items), 0, 0), items)

    def history(self) -> tuple[HistoryItemView, ...]:
        return self.history_items

    def remove_history(
        self, task_id: str, *, delete_output: bool
    ) -> CommandResult[HistoryRemovalView]:
        return CommandResult.succeeded(HistoryRemovalView(task_id, delete_output, False))

    def task_details(self, task_id: str) -> CommandResult[TaskDetailsView]:
        item = self.items.get(task_id)
        if item is None:
            return CommandResult.failed(command_message("error.task_not_found"))
        return CommandResult.succeeded(
            TaskDetailsView(item, "https://example.com/media", "C:\\", ())
        )

    def load_settings(self) -> SettingsView:
        return SettingsView("C:\\", "video.1080p.mp4.auto", 2)

    def dependency_status(self) -> tuple[DependencyStatusView, ...]:
        return self.dependencies

    def acknowledge_startup_check(self) -> CommandResult[SettingsView]:
        return CommandResult.succeeded(self.load_settings())

    def save_settings(
        self,
        *,
        default_output_directory: str,
        default_preset_id: str,
        concurrent_downloads: int,
        default_audio_preset_id: str,
        theme: str,
        language: str,
    ) -> CommandResult[SettingsView]:
        return CommandResult.succeeded(
            SettingsView(
                default_output_directory,
                default_preset_id,
                concurrent_downloads,
                default_audio_preset_id,
                theme,
                language,
            )
        )

    def _action_result(self, task_id: str) -> CommandResult[DownloadItemView]:
        self.action_started.set()
        self.allow_action.wait(timeout=5)
        item = self.items[task_id]
        return CommandResult.succeeded(item)


def _item(
    task_id: TaskId,
    title: str,
    fraction: float | None,
    *,
    status: DownloadStatus = DownloadStatus.DOWNLOADING,
) -> DownloadItemView:
    progress = (
        ProgressView("downloading", fraction, 80, 100, None, None) if fraction is not None else None
    )
    return DownloadItemView(
        task_id=str(task_id),
        attempt_id=str(AttemptId.new()),
        title=title,
        preset_kind=MediaKind.VIDEO,
        quality="1080p",
        container="mp4",
        status=status,
        created_at=_at(0).value,
        updated_at=_at(0).value,
        progress=progress,
        failure=None,
        output_path=None,
        actions=TaskActionsView(True, True, True, True, True, False),
    )


def _configuration() -> MediaConfigurationView:
    return MediaConfigurationView(
        configuration_id="configuration-id",
        source_url="https://example.com/media",
        title="Media",
        source_name="Example",
        uploader=None,
        duration_seconds=None,
        thumbnail_url=None,
        is_live=False,
        playlist_item_count=None,
        presets=(),
    )


def _configuration_with_presets() -> MediaConfigurationView:
    return MediaConfigurationView(
        configuration_id="configuration-id",
        source_url="https://example.com/media",
        title="A deliberately long media title that remains readable in the compact card",
        source_name="Example",
        uploader=None,
        duration_seconds=None,
        thumbnail_url=None,
        is_live=False,
        playlist_item_count=None,
        presets=(
            PresetOptionView("video.1080p.mp4.auto", MediaKind.VIDEO, "1080p", "mp4", None, True),
            PresetOptionView(
                "audio.best.mp3.auto",
                MediaKind.AUDIO,
                "best",
                "mp3",
                None,
                True,
                requires_processing=True,
            ),
        ),
    )


def _history_item(item: DownloadItemView) -> HistoryItemView:
    return HistoryItemView(
        task_id=item.task_id,
        title=item.title,
        status=item.status,
        preset_kind=item.preset_kind,
        quality=item.quality,
        container=item.container,
        finished_at=item.updated_at,
        output_path=item.output_path,
        failure=None,
        actions=item.actions,
    )


def _progress_event(
    task_id: TaskId, attempt_id: AttemptId, downloaded: int, total: int, seconds: int
) -> TaskProgressChanged:
    return TaskProgressChanged(
        task_id,
        attempt_id,
        ProgressSnapshot.downloading(
            captured_at=_at(seconds), downloaded_bytes=downloaded, total_bytes=total
        ),
        _at(seconds),
    )


def _at(seconds: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 9, 7, tzinfo=UTC).replace(second=seconds))


def _wait_until(qtbot: object, condition: object) -> None:
    wait_until = getattr(qtbot, "waitUntil", None)
    if wait_until is None:
        raise AssertionError("pytest-qt did not provide qtbot.waitUntil")
    wait_until(condition, timeout=2_000)


def _wait(qtbot: object, milliseconds: int) -> None:
    wait = getattr(qtbot, "wait", None)
    if wait is None:
        raise AssertionError("pytest-qt did not provide qtbot.wait")
    wait(milliseconds)


def _add_widget(qtbot: object, widget: QWidget) -> None:
    add_widget = getattr(qtbot, "addWidget", None)
    if add_widget is None:
        raise AssertionError("pytest-qt did not provide qtbot.addWidget")
    add_widget(widget)
