"""The stable desktop shell and its presentation-only lifecycle concerns."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from PySide6.QtCore import QEvent, QObject, QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QGuiApplication, QIcon, QKeySequence, QResizeEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mediaflow.presentation.design import TOKENS, ShellWidth, ThemeController, ThemeMode
from mediaflow.presentation.shell import (
    NavigationDestination,
    PlaceholderPage,
    brand_icon,
    footer_brand_icon,
    make_navigation_button,
)
from mediaflow.presentation.strings import Localizer, StringKey


class UiThreadViolation(RuntimeError):
    """A widget mutation was attempted outside its owning Qt thread."""


def assert_ui_thread(owner: QObject) -> None:
    """Fail fast in presentation code before a cross-thread widget mutation."""

    if owner.thread() != QThread.currentThread():
        raise UiThreadViolation("Qt widgets may only be updated from their owning thread")


class MediaFlowWindow(QMainWindow):
    """Own the reusable app chrome; workflow screens are introduced in later milestones."""

    _MINIMUM_WIDTH = 700
    _MINIMUM_HEIGHT = 500
    _COMPACT_WIDTH = 900
    _LARGE_WIDTH = 1200
    _FULL_SIDEBAR_WIDTH = 232
    _COMPACT_SIDEBAR_WIDTH = 68
    _GEOMETRY_KEY = "presentation/window_geometry"
    closed = Signal()

    def __init__(
        self,
        *,
        geometry_store: QSettings | None = None,
        localizer: Localizer | None = None,
        theme_controller: ThemeController | None = None,
    ) -> None:
        super().__init__()
        assert_ui_thread(self)
        self._geometry_store = geometry_store
        self._localizer = localizer or Localizer()
        application = QApplication.instance()
        if theme_controller is None:
            if not isinstance(application, QApplication):
                raise RuntimeError("MediaFlowWindow requires an active QApplication")
            theme_controller = ThemeController(application)
        self._theme_controller = theme_controller
        self._navigation_buttons: dict[NavigationDestination, QToolButton] = {}
        self._pages: dict[NavigationDestination, QWidget] = {}
        self._shell_width = ShellWidth.STANDARD
        self._close_request_handler: Callable[[], bool] | None = None
        self._close_permitted = False

        self.setObjectName("mediaflowWindow")
        self.setWindowTitle(self._localizer.text(StringKey.APP_NAME))
        self.setMinimumSize(self._MINIMUM_WIDTH, self._MINIMUM_HEIGHT)
        self.resize(1000, 700)
        self._build_shell()
        self._restore_geometry()
        self._apply_shell_width()

    @property
    def content_stack(self) -> QStackedWidget:
        """Expose the stack for presentation tests and future screen replacement."""

        return self._content_stack

    @property
    def current_destination(self) -> NavigationDestination:
        """Return the selected stable navigation item."""

        return self._current_destination

    @property
    def shell_width(self) -> ShellWidth:
        """Return the active responsive shell state."""

        return self._shell_width

    @property
    def theme_controller(self) -> ThemeController:
        """Provide the presentation-owned theme controller to future settings UI."""

        return self._theme_controller

    def navigation_button(self, destination: NavigationDestination) -> QToolButton:
        """Find the one persistent navigation control for a destination."""

        return self._navigation_buttons[destination]

    def navigate(self, destination: NavigationDestination) -> None:
        """Select an existing page without creating a duplicate screen instance."""

        assert_ui_thread(self)
        self._current_destination = destination
        self._content_stack.setCurrentWidget(self._pages[destination])
        self._navigation_buttons[destination].setChecked(True)

    def replace_page(self, destination: NavigationDestination, page: QWidget) -> None:
        """Replace one milestone placeholder while retaining shell navigation state."""

        assert_ui_thread(self)
        current = self._pages[destination]
        if current is page:
            return
        index = self._content_stack.indexOf(current)
        self._content_stack.removeWidget(current)
        current.deleteLater()
        self._content_stack.insertWidget(index, page)
        self._pages[destination] = page
        if self._current_destination is destination:
            self._content_stack.setCurrentWidget(page)

    def go_home(self) -> None:
        """Implement the global back-to-Home intent used by shell shortcuts."""

        self.navigate(NavigationDestination.HOME)

    def set_theme_mode(self, mode: ThemeMode) -> None:
        """Change palette without rebuilding the shell or altering selected navigation."""

        self._theme_controller.set_mode(mode)

    def set_close_request_handler(self, handler: Callable[[], bool] | None) -> None:
        """Install the application-owned lifecycle decision for user close requests."""

        assert_ui_thread(self)
        self._close_request_handler = handler

    def close_after_shutdown(self) -> None:
        """Close once the lifecycle owner has received a clean shutdown report."""

        assert_ui_thread(self)
        self._close_permitted = True
        self.close()

    def clamp_geometry(self) -> None:
        """Keep restored geometry visible when a monitor was removed or changed."""

        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        width = min(max(self.minimumWidth(), self.width()), available.width())
        height = min(max(self.minimumHeight(), self.height()), available.height())
        maximum_x = available.x() + available.width() - width
        maximum_y = available.y() + available.height() - height
        x = min(max(self.x(), available.x()), maximum_x)
        y = min(max(self.y(), available.y()), maximum_y)
        self.setGeometry(x, y, width, height)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._apply_shell_width()

    def event(self, event: QEvent) -> bool:
        if event.type() is QEvent.Type.ScreenChangeInternal:
            QTimer.singleShot(0, self.clamp_geometry)
        return super().event(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        if (
            not self._close_permitted
            and self._close_request_handler is not None
            and not self._close_request_handler()
        ):
            event.ignore()
            return
        self._save_geometry()
        self.closed.emit()
        super().closeEvent(event)

    def _build_shell(self) -> None:
        root = QWidget(self)
        root.setObjectName("shellRoot")
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self._sidebar = QFrame(root)
        self._sidebar.setObjectName("sidebar")
        sidebar_layout = QVBoxLayout(self._sidebar)
        sidebar_layout.setContentsMargins(
            TOKENS.spacing.standard,
            TOKENS.spacing.section,
            TOKENS.spacing.standard,
            TOKENS.spacing.standard,
        )
        sidebar_layout.setSpacing(TOKENS.spacing.small)
        self._brand_header = QWidget(self._sidebar)
        self._brand_header.setObjectName("brandHeader")
        brand_layout = QHBoxLayout(self._brand_header)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(TOKENS.spacing.compact)
        self._brand_mark = QLabel(self._brand_header)
        self._brand_mark.setObjectName("brandMark")
        self._brand_mark.setPixmap(brand_icon().pixmap(44, 44, QIcon.Mode.Normal, QIcon.State.Off))
        self._brand_mark.setFixedSize(44, 44)
        self._brand_mark.setAccessibleName(self._localizer.text(StringKey.APP_NAME))
        brand_layout.addWidget(self._brand_mark)
        self._brand_copy = QWidget(self._brand_header)
        brand_copy_layout = QVBoxLayout(self._brand_copy)
        brand_copy_layout.setContentsMargins(0, 0, 0, 0)
        brand_copy_layout.setSpacing(0)
        self._application_name = QLabel(self._localizer.text(StringKey.APP_NAME), self._brand_copy)
        self._application_name.setObjectName("applicationName")
        self._application_tagline = QLabel(
            self._localizer.text(StringKey.APP_TAGLINE), self._brand_copy
        )
        self._application_tagline.setObjectName("applicationTagline")
        brand_copy_layout.addWidget(self._application_name)
        brand_copy_layout.addWidget(self._application_tagline)
        brand_layout.addWidget(self._brand_copy, 1)
        sidebar_layout.addWidget(self._brand_header)
        sidebar_layout.addSpacing(TOKENS.spacing.section)

        self._content_stack = QStackedWidget(root)
        self._content_stack.setObjectName("contentArea")
        self._navigation_group = QButtonGroup(self)
        self._navigation_group.setExclusive(True)
        for destination, title_key, description_key in _PAGE_DEFINITIONS:
            page = PlaceholderPage(
                title_key=title_key,
                description_key=description_key,
                localizer=self._localizer,
                parent=self._content_stack,
            )
            self._pages[destination] = page
            self._content_stack.addWidget(page)
            button = make_navigation_button(
                destination=destination,
                label_key=title_key,
                localizer=self._localizer,
                style=self.style(),
                parent=self._sidebar,
            )
            self._navigation_group.addButton(button)
            button.clicked.connect(
                lambda _checked=False, selected=destination: self.navigate(selected)
            )
            self._navigation_buttons[destination] = button
            sidebar_layout.addWidget(button)

        sidebar_layout.addStretch(1)
        self._brand_footer = QWidget(self._sidebar)
        self._brand_footer.setObjectName("brandFooter")
        footer_layout = QVBoxLayout(self._brand_footer)
        footer_layout.setContentsMargins(TOKENS.spacing.compact, 0, 0, 0)
        footer_layout.setSpacing(TOKENS.spacing.small)
        footer_identity = QWidget(self._brand_footer)
        identity_layout = QHBoxLayout(footer_identity)
        identity_layout.setContentsMargins(0, 0, 0, 0)
        identity_layout.setSpacing(TOKENS.spacing.small)
        self._footer_mark = QLabel(footer_identity)
        self._footer_mark.setObjectName("footerMark")
        self._footer_mark.setPixmap(footer_brand_icon().pixmap(24, 24))
        self._footer_mark.setFixedSize(24, 24)
        identity_layout.addWidget(self._footer_mark)
        identity_copy = QWidget(footer_identity)
        identity_copy_layout = QVBoxLayout(identity_copy)
        identity_copy_layout.setContentsMargins(0, 0, 0, 0)
        identity_copy_layout.setSpacing(0)
        footer_name = QLabel(self._localizer.text(StringKey.APP_NAME), identity_copy)
        footer_name.setObjectName("footerName")
        footer_version = QLabel(self._localizer.text(StringKey.APP_VERSION), identity_copy)
        footer_version.setObjectName("footerVersion")
        identity_copy_layout.addWidget(footer_name)
        identity_copy_layout.addWidget(footer_version)
        identity_layout.addWidget(identity_copy, 1)
        footer_layout.addWidget(footer_identity)
        self._footer_tagline = QLabel(
            self._localizer.text(StringKey.APP_FOOTER_TAGLINE), self._brand_footer
        )
        self._footer_tagline.setObjectName("footerTagline")
        self._footer_tagline.setWordWrap(True)
        footer_layout.addWidget(self._footer_tagline)
        sidebar_layout.addWidget(self._brand_footer)

        root_layout.addWidget(self._sidebar)
        root_layout.addWidget(self._content_stack, 1)
        self.setCentralWidget(root)
        self._install_navigation_shortcuts()
        self.navigate(NavigationDestination.HOME)

    def _install_navigation_shortcuts(self) -> None:
        shortcuts: Mapping[QKeySequence, NavigationDestination] = {
            QKeySequence("Ctrl+Home"): NavigationDestination.HOME,
            QKeySequence("Ctrl+J"): NavigationDestination.DOWNLOADS,
            QKeySequence("Ctrl+H"): NavigationDestination.HISTORY,
            QKeySequence("Ctrl+,"): NavigationDestination.SETTINGS,
        }
        for shortcut, destination in shortcuts.items():
            action = QAction(self)
            action.setShortcut(shortcut)
            action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            action.triggered.connect(
                lambda _checked=False, selected=destination: self.navigate(selected)
            )
            self.addAction(action)

    def _apply_shell_width(self) -> None:
        width = self.width()
        shell_width = (
            ShellWidth.LARGE
            if width >= self._LARGE_WIDTH
            else ShellWidth.STANDARD
            if width >= self._COMPACT_WIDTH
            else ShellWidth.COMPACT
        )
        if shell_width is self._shell_width and self._sidebar.minimumWidth() > 0:
            return
        self._shell_width = shell_width
        compact = shell_width is ShellWidth.COMPACT
        sidebar_width = self._COMPACT_SIDEBAR_WIDTH if compact else self._FULL_SIDEBAR_WIDTH
        self._sidebar.setFixedWidth(sidebar_width)
        self._brand_copy.setVisible(not compact)
        self._brand_footer.setVisible(not compact)
        for button in self._navigation_buttons.values():
            button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonIconOnly
                if compact
                else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
            )
            button.setToolTip(button.accessibleName())

    def _restore_geometry(self) -> None:
        if self._geometry_store is None:
            return
        geometry = self._geometry_store.value(self._GEOMETRY_KEY)
        if geometry is not None:
            self.restoreGeometry(geometry)
        self.clamp_geometry()

    def _save_geometry(self) -> None:
        if self._geometry_store is None:
            return
        self._geometry_store.setValue(self._GEOMETRY_KEY, self.saveGeometry())
        self._geometry_store.sync()


_PAGE_DEFINITIONS: tuple[tuple[NavigationDestination, StringKey, StringKey], ...] = (
    (NavigationDestination.HOME, StringKey.HOME, StringKey.HOME_PLACEHOLDER),
    (NavigationDestination.DOWNLOADS, StringKey.DOWNLOADS, StringKey.DOWNLOADS_PLACEHOLDER),
    (NavigationDestination.HISTORY, StringKey.HISTORY, StringKey.HISTORY_PLACEHOLDER),
    (NavigationDestination.SETTINGS, StringKey.SETTINGS, StringKey.SETTINGS_PLACEHOLDER),
)
