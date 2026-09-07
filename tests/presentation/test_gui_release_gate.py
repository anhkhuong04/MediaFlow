"""Offline GUI release-gate scenarios built only on the public C8 contract."""

from __future__ import annotations

from dataclasses import replace
from threading import Thread

from PySide6.QtWidgets import QWidget

from mediaflow.application import (
    CommandResult,
    DownloadStatus,
    TaskActionsView,
    TaskStateChanged,
    UserMessage,
)
from mediaflow.application.messages import command_message
from mediaflow.domain import AttemptId, TaskId, TaskState, UtcTimestamp
from mediaflow.presentation.bridge import PresentationCommandRunner, QtEventBridge
from mediaflow.presentation.controllers import DownloadsController, HomeController, TaskAction
from mediaflow.presentation.downloads import DownloadsPage
from mediaflow.presentation.home import HomePage
from tests.presentation.test_bridge_and_controllers import (
    FakePresentationFacade,
    _configuration_with_presets,
    _item,
    _progress_event,
    _wait_until,
)


def test_fake_facade_covers_home_analysis_enqueue_and_download_state_matrix(qtbot: object) -> None:
    """Exercise the V1 happy and error states without a network engine or Qt-thread I/O."""

    task_id = TaskId.new()
    facade = FakePresentationFacade(items={str(task_id): _item(task_id, "Release fixture", None)})
    bridge = QtEventBridge(facade, progress_interval_ms=1)
    runner = PresentationCommandRunner(bridge)
    home_controller = HomeController(facade, bridge, runner)
    downloads_controller = DownloadsController(facade, runner)
    home = HomePage(home_controller)
    downloads = DownloadsPage(downloads_controller)
    _add_widget(qtbot, home)
    _add_widget(qtbot, downloads)
    bridge.command_completed.connect(home_controller.handle_completion)
    bridge.command_completed.connect(downloads_controller.handle_completion)
    bridge.application_event.connect(downloads_controller.handle_event)
    bridge.start()
    downloads_controller.refresh()
    home.show()
    downloads.show()

    home.url_input.setText("https://example.com/release-fixture")
    home.analyze_button.click()
    facade.analysis_result.set_result(CommandResult.succeeded(_configuration_with_presets()))
    _wait_until(qtbot, lambda: home_controller.state.configuration is not None)
    home.set_default_output_directory("C:\\Downloads")
    facade.allow_action.set()
    home.add_button.click()
    _wait_until(qtbot, lambda: not home_controller.state.enqueue.is_busy)
    assert home.analysis_status.isVisible()

    states = (
        DownloadStatus.DOWNLOADING,
        DownloadStatus.PROCESSING,
        DownloadStatus.COMPLETED,
        DownloadStatus.FAILED,
    )
    for sequence, status in enumerate(states, start=1):
        item = _item(task_id, "Release fixture", 0.5, status=status)
        if status is DownloadStatus.FAILED:
            item = replace(
                item,
                failure=UserMessage("error.network.title", "error.network.body", "network.failed"),
            )
        facade.items[str(task_id)] = item
        facade.events.publish(
            TaskStateChanged(
                task_id,
                AttemptId.new(),
                TaskState.QUEUED,
                TaskState(status.value),
                _at(sequence),
            )
        )
        _wait_until(
            qtbot,
            lambda expected=status: downloads._cards[str(task_id)]._item.status is expected,
        )

    assert downloads._cards[str(task_id)].failure.isVisible()

    failed_analysis = FakePresentationFacade()
    failed_bridge = QtEventBridge(failed_analysis)
    failed_runner = PresentationCommandRunner(failed_bridge)
    failed_controller = HomeController(failed_analysis, failed_bridge, failed_runner)
    failed_home = HomePage(failed_controller)
    _add_widget(qtbot, failed_home)
    failed_bridge.command_completed.connect(failed_controller.handle_completion)
    failed_bridge.start()
    failed_home.show()
    failed_home.url_input.setText("https://example.com/unavailable")
    failed_home.analyze_button.click()
    failed_analysis.analysis_result.set_result(
        CommandResult.failed(command_message("error.network"))
    )
    _wait_until(qtbot, lambda: failed_home.error_label.isVisible())

    failed_bridge.close()
    failed_runner.close()
    bridge.close()
    runner.close()


def test_progress_burst_preserves_download_order_selection_and_widget_focus(qtbot: object) -> None:
    """A live progress burst updates one stable card instead of rebuilding the list."""

    task_ids = tuple(TaskId.new() for _ in range(60))
    facade = FakePresentationFacade(
        items={
            str(task_id): _item(task_id, f"Task {index}", 0.1)
            for index, task_id in enumerate(task_ids)
        }
    )
    bridge = QtEventBridge(facade, progress_interval_ms=1)
    runner = PresentationCommandRunner(bridge)
    controller = DownloadsController(facade, runner)
    page = DownloadsPage(controller)
    _add_widget(qtbot, page)
    bridge.command_completed.connect(controller.handle_completion)
    bridge.application_event.connect(controller.handle_event)
    bridge.start()
    page.show()
    controller.refresh()
    _wait_until(qtbot, lambda: len(page._cards) == len(task_ids))

    selected = task_ids[30]
    controller.select_task(str(selected))
    selected_card = page._cards[str(selected)]
    selected_card.setFocus()
    original_order = tuple(controller_item.task_id for controller_item in controller.state.items)
    facade.items[str(selected)] = _item(selected, "Task 30", 0.99)

    def publish_burst() -> None:
        for value in range(1, 301):
            facade.events.publish(
                _progress_event(selected, AttemptId.new(), value, 300, value % 59)
            )

    worker = Thread(target=publish_burst, name="gui-release-progress-burst")
    worker.start()
    worker.join(timeout=5)
    assert not worker.is_alive()
    _wait_until(qtbot, lambda: page._cards[str(selected)].progress.value() == 99)

    assert tuple(item.task_id for item in controller.state.items) == original_order
    assert controller.state.selected_task_id == str(selected)
    assert page._cards[str(selected)] is selected_card
    assert selected_card.hasFocus()
    bridge.close()
    runner.close()


def test_interrupted_recovery_row_is_never_rendered_as_downloading(qtbot: object) -> None:
    """The UI renders only persisted/core-projected recovery capability, never an invented state."""

    task_id = TaskId.new()
    interrupted = replace(
        _item(task_id, "Recovered task", None),
        status=DownloadStatus.INTERRUPTED,
        actions=TaskActionsView(False, False, True, True, False, False),
    )
    facade = FakePresentationFacade(items={str(task_id): interrupted})
    bridge = QtEventBridge(facade)
    runner = PresentationCommandRunner(bridge)
    controller = DownloadsController(facade, runner)
    page = DownloadsPage(controller)
    _add_widget(qtbot, page)
    bridge.command_completed.connect(controller.handle_completion)
    bridge.start()
    page.show()
    controller.refresh()
    _wait_until(qtbot, lambda: str(task_id) in page._cards)

    card = page._cards[str(task_id)]
    assert card._item.status is DownloadStatus.INTERRUPTED
    assert card.stage.text() != "Downloading"
    assert card._buttons[TaskAction.RESUME].isVisible()
    assert card._buttons[TaskAction.RESTART].isVisible()
    assert not card._buttons[TaskAction.CANCEL].isVisible()
    bridge.close()
    runner.close()


def _at(second: int) -> UtcTimestamp:
    from datetime import UTC, datetime

    return UtcTimestamp(datetime(2026, 9, 7, tzinfo=UTC).replace(second=second))


def _add_widget(qtbot: object, widget: QWidget) -> None:
    add_widget = getattr(qtbot, "addWidget", None)
    if add_widget is None:
        raise AssertionError("pytest-qt did not provide qtbot.addWidget")
    add_widget(widget)
