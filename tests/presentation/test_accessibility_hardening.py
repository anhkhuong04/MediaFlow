from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QBoxLayout, QWidget

from mediaflow.application import DownloadStatus, DownloadSummaryView
from mediaflow.domain import TaskId
from mediaflow.presentation.bridge import PresentationCommandRunner, QtEventBridge
from mediaflow.presentation.controllers import (
    DownloadsController,
    DownloadsState,
    HomeController,
    SettingsController,
)
from mediaflow.presentation.design import TOKENS, contrast_ratio
from mediaflow.presentation.downloads import DownloadCard, DownloadsPage
from mediaflow.presentation.home import HomePage
from mediaflow.presentation.output_actions import QtOutputLauncher
from mediaflow.presentation.settings import SettingsPage
from mediaflow.presentation.strings import _TRANSLATIONS, Language, Localizer, StringKey
from tests.presentation.test_bridge_and_controllers import FakePresentationFacade, _item


def test_translation_catalog_is_complete_and_has_a_visible_fallback() -> None:
    keys = set(StringKey)

    assert all(set(catalog) == keys for catalog in _TRANSLATIONS.values())
    assert Localizer(Language.VIETNAMESE).text(StringKey.OPEN_LOGS) == "Mở nhật ký"
    assert Localizer().text("unknown.key") == "[unknown.key]"


def test_theme_tokens_keep_primary_and_secondary_copy_readable() -> None:
    for palette in (TOKENS.light, TOKENS.dark):
        assert contrast_ratio(palette.text, palette.window) >= 4.5
        assert contrast_ratio(palette.text_secondary, palette.window) >= 4.5
        assert contrast_ratio(palette.disabled_text, palette.surface) >= 3.0


def test_home_and_settings_primary_controls_have_keyboard_names(qtbot: object) -> None:
    facade = FakePresentationFacade()
    bridge = QtEventBridge(facade)
    runner = PresentationCommandRunner(bridge)
    home = HomePage(HomeController(facade, bridge, runner))
    settings = SettingsPage(SettingsController(facade, runner))
    _add_widget(qtbot, home)
    _add_widget(qtbot, settings)

    for control in (
        home.url_input,
        home.paste_button,
        home.analyze_button,
        home.add_button,
        settings.theme,
        settings.folder,
        settings.save_button,
    ):
        assert control.accessibleName()
        assert control.accessibleDescription()

    assert home.url_input.focusPolicy() is Qt.FocusPolicy.StrongFocus
    assert home.paste_button.focusPolicy() is Qt.FocusPolicy.StrongFocus
    bridge.close()
    runner.close()


def test_home_compact_layout_stacks_primary_rows_and_hides_horizontal_scroll(qtbot: object) -> None:
    facade = FakePresentationFacade()
    bridge = QtEventBridge(facade)
    runner = PresentationCommandRunner(bridge)
    page = HomePage(HomeController(facade, bridge, runner))
    _add_widget(qtbot, page)
    page.resize(700, 500)
    page.show()
    _wait(qtbot, 10)

    assert page.horizontalScrollBarPolicy() is Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert page._url_row.direction() is QBoxLayout.Direction.TopToBottom
    assert page._location_row.direction() is QBoxLayout.Direction.TopToBottom
    bridge.close()
    runner.close()


def test_compact_cards_stack_actions_without_discarding_accessibility(qtbot: object) -> None:
    facade = FakePresentationFacade()
    bridge = QtEventBridge(facade)
    runner = PresentationCommandRunner(bridge)
    controller = DownloadsController(facade, runner)
    parent = QWidget()
    _add_widget(qtbot, parent)
    card = DownloadCard(
        _item(TaskId.new(), "A very long media title " * 8, None),
        controller,
        Localizer(Language.VIETNAMESE),
        QtOutputLauncher(),
        parent,
    )
    parent.resize(480, 400)
    card.setGeometry(0, 0, 480, 300)
    parent.show()
    card.show()
    _wait(qtbot, 10)

    assert card.actions_layout.direction() is QBoxLayout.Direction.TopToBottom
    assert card.open_file.accessibleName()
    assert card.details_button.accessibleName()
    bridge.close()
    runner.close()


def test_terminal_status_is_announced_once_not_for_progress_ticks(
    qtbot: object, qapp: QApplication
) -> None:
    del qapp
    facade = FakePresentationFacade()
    bridge = QtEventBridge(facade)
    runner = PresentationCommandRunner(bridge)
    controller = DownloadsController(facade, runner)
    task_id = TaskId.new()
    item = _item(task_id, "Example", 0.2)
    page = DownloadsPage(controller)
    _add_widget(qtbot, page)
    page.show()
    page.render_state(DownloadsState(items=(item,), summary=DownloadSummaryView(1, 0, 0, 0)))
    assert not page.status_announcement.isVisible()

    completed = _item(task_id, "Example", None, status=DownloadStatus.COMPLETED)
    page.render_state(DownloadsState(items=(completed,), summary=DownloadSummaryView(0, 0, 1, 0)))
    assert page.status_announcement.isVisible()
    message = page.status_announcement.text()
    page.render_state(DownloadsState(items=(completed,), summary=DownloadSummaryView(0, 0, 1, 0)))
    assert page.status_announcement.text() == message
    bridge.close()
    runner.close()


def test_downloads_handles_large_list_with_long_titles_and_unknown_telemetry(qtbot: object) -> None:
    facade = FakePresentationFacade()
    bridge = QtEventBridge(facade)
    runner = PresentationCommandRunner(bridge)
    controller = DownloadsController(facade, runner)
    page = DownloadsPage(controller, localizer=Localizer(Language.VIETNAMESE))
    _add_widget(qtbot, page)
    page.show()
    items = tuple(
        _item(TaskId.new(), f"Tựa đề media rất dài {index} " * 8, None) for index in range(100)
    )

    page.render_state(DownloadsState(items=items, summary=DownloadSummaryView(100, 0, 0, 0)))

    assert len(page._cards) == 100
    assert page.horizontalScrollBarPolicy() is Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert all(card.title.wordWrap() for card in page._cards.values())
    assert all(card.progress.isHidden() for card in page._cards.values())
    bridge.close()
    runner.close()


def _add_widget(qtbot: object, widget: QWidget) -> None:
    add_widget = getattr(qtbot, "addWidget", None)
    if add_widget is None:
        raise AssertionError("pytest-qt did not provide qtbot.addWidget")
    add_widget(widget)


def _wait(qtbot: object, milliseconds: int) -> None:
    wait = getattr(qtbot, "wait", None)
    if wait is None:
        raise AssertionError("pytest-qt did not provide qtbot.wait")
    wait(milliseconds)
