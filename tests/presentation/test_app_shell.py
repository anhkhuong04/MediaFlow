from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QScrollArea

from mediaflow.presentation import (
    MediaFlowWindow,
    NavigationDestination,
    ShellWidth,
    ThemeMode,
)
from mediaflow.presentation.strings import Language, Localizer, StringKey


def test_navigation_uses_one_page_per_destination_and_keyboard_intent(qtbot: object) -> None:
    window = MediaFlowWindow()
    _add_widget(qtbot, window)
    window.show()

    original_pages = [
        window.content_stack.widget(index) for index in range(window.content_stack.count())
    ]
    downloads = window.navigation_button(NavigationDestination.DOWNLOADS)
    downloads.setFocus()
    QTest.keyClick(downloads, Qt.Key.Key_Space)

    assert downloads.isChecked()
    assert downloads.focusPolicy() is Qt.FocusPolicy.StrongFocus
    assert downloads.accessibleName() == "Downloads"
    assert downloads.toolTip() == "Downloads"
    assert "QToolButton#navigationItem:focus" in _application_stylesheet()

    _trigger_shortcut(window, "Ctrl+H")
    assert _current_destination(window) is NavigationDestination.HISTORY

    window.go_home()
    assert _current_destination(window) is NavigationDestination.HOME
    assert window.content_stack.count() == 4
    assert [
        window.content_stack.widget(index) for index in range(window.content_stack.count())
    ] == original_pages


def test_theme_change_preserves_navigation_and_keyboard_focus(qtbot: object) -> None:
    window = MediaFlowWindow()
    _add_widget(qtbot, window)
    window.show()
    settings = window.navigation_button(NavigationDestination.SETTINGS)
    settings.click()
    settings.setFocus()

    window.set_theme_mode(ThemeMode.DARK)

    assert window.theme_controller.mode is ThemeMode.DARK
    assert _current_destination(window) is NavigationDestination.SETTINGS
    assert settings is window.navigation_button(NavigationDestination.SETTINGS)
    assert "#1b1d21" in _application_stylesheet()
    assert "#79b8ff" in _application_stylesheet()

    window.set_theme_mode(ThemeMode.SYSTEM)
    window.theme_controller.apply_system_color_scheme(Qt.ColorScheme.Light)

    assert window.theme_controller.mode.value == ThemeMode.SYSTEM.value
    assert "#f5f6f8" in _application_stylesheet()
    assert "#005fb8" in _application_stylesheet()


def test_compact_shell_switches_navigation_to_accessible_icon_only(qtbot: object) -> None:
    window = MediaFlowWindow()
    _add_widget(qtbot, window)
    window.show()
    window.resize(800, 600)

    home = window.navigation_button(NavigationDestination.HOME)
    sidebar = window.findChild(QFrame, "sidebar")

    assert window.shell_width is ShellWidth.COMPACT
    assert home.toolButtonStyle() is Qt.ToolButtonStyle.ToolButtonIconOnly
    assert home.accessibleName() == "Home"
    assert home.toolTip() == "Home"
    assert sidebar is not None
    assert sidebar.width() == 68
    assert window.content_stack.width() > 0
    assert not window.findChildren(QScrollArea)

    window.resize(1200, 700)
    assert window.shell_width.value == ShellWidth.LARGE.value
    assert home.toolButtonStyle() is Qt.ToolButtonStyle.ToolButtonTextBesideIcon


def test_sidebar_uses_packaged_brand_and_navigation_artwork(qtbot: object) -> None:
    window = MediaFlowWindow()
    _add_widget(qtbot, window)
    window.show()

    tagline = window.findChild(QLabel, "applicationTagline")
    footer_tagline = window.findChild(QLabel, "footerTagline")
    brand_mark = window.findChild(QLabel, "brandMark")
    footer_mark = window.findChild(QLabel, "footerMark")

    assert tagline is not None and tagline.text() == "Download. Keep. Enjoy."
    assert footer_tagline is not None and "simpler way" in footer_tagline.text()
    assert brand_mark is not None and brand_mark.pixmap() is not None
    assert footer_mark is not None and footer_mark.pixmap() is not None
    assert all(
        not window.navigation_button(destination).icon().isNull()
        for destination in NavigationDestination
    )

    window.resize(800, 600)

    assert not tagline.isVisible()
    assert not footer_tagline.isVisible()
    assert brand_mark.isVisible()


def test_geometry_is_clamped_and_persisted_in_the_injected_store(
    qtbot: object, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "presentation.ini"), QSettings.Format.IniFormat)
    window = MediaFlowWindow(geometry_store=settings)
    _add_widget(qtbot, window)
    window.show()
    window.setGeometry(-500, -500, 760, 560)
    window.clamp_geometry()

    screen = window.screen() or QApplication.primaryScreen()
    assert screen is not None
    available = screen.availableGeometry()
    geometry = window.geometry()
    assert geometry.intersects(available)
    assert geometry.left() >= available.left()
    assert geometry.top() >= available.top()

    window.close()
    assert settings.value("presentation/window_geometry") is not None


def test_localizer_keeps_user_facing_copy_out_of_widgets() -> None:
    localizer = Localizer(Language.VIETNAMESE)

    assert localizer.text(StringKey.DOWNLOADS) == "Tải xuống"
    assert localizer.text(StringKey.SHELL_STATUS_READY) == "Khung ứng dụng đã sẵn sàng"


def _add_widget(qtbot: object, widget: MediaFlowWindow) -> None:
    add_widget = getattr(qtbot, "addWidget", None)
    if add_widget is None:
        raise AssertionError("pytest-qt did not provide qtbot.addWidget")
    add_widget(widget)


def _application_stylesheet() -> str:
    application = QApplication.instance()
    if not isinstance(application, QApplication):
        raise AssertionError("A QApplication is required for presentation tests")
    return application.styleSheet()


def _current_destination(window: MediaFlowWindow) -> NavigationDestination:
    return window.current_destination


def _trigger_shortcut(window: MediaFlowWindow, shortcut: str) -> None:
    key_sequence = QKeySequence(shortcut)
    action = next(
        action
        for action in window.actions()
        if action.shortcut().matches(key_sequence) is QKeySequence.SequenceMatch.ExactMatch
    )
    action.trigger()
