"""Windows lifecycle integration owned by the Qt composition root."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QStyle, QSystemTrayIcon

from mediaflow.application import ApplicationEvent, OutputReady, ShutdownReport, TaskFailed
from mediaflow.presentation.coordinator import PresentationCoordinator
from mediaflow.presentation.shell import NavigationDestination
from mediaflow.presentation.strings import Localizer, StringKey
from mediaflow.presentation.window import MediaFlowWindow, assert_ui_thread


class _ShutdownThread(QThread):
    completed = Signal(object)

    def __init__(self, shutdown: Callable[[], ShutdownReport | None]) -> None:
        super().__init__()
        self._shutdown = shutdown

    def run(self) -> None:
        try:
            self.completed.emit(self._shutdown())
        except Exception as error:  # surfaced as an honest non-clean lifecycle result
            self.completed.emit(error)


class DesktopLifecycle(QObject):
    """Translate close/tray intents into the C7 shutdown policy without force-killing work."""

    shutdown_completed = Signal(object)

    def __init__(
        self,
        application: QApplication,
        window: MediaFlowWindow,
        presentation: PresentationCoordinator,
        shutdown: Callable[[], ShutdownReport | None],
        open_logs: Callable[[], bool],
        localizer: Localizer,
    ) -> None:
        super().__init__(window)
        assert_ui_thread(self)
        self._application = application
        self._window = window
        self._presentation = presentation
        self._shutdown = shutdown
        self._open_logs = open_logs
        self._localizer = localizer
        self._shutdown_thread: _ShutdownThread | None = None
        self._shutdown_started = False
        self._notification_task_id: str | None = None
        self._tray = QSystemTrayIcon(self._tray_icon(), self)
        self._tray.setToolTip(localizer.text(StringKey.APP_NAME))
        self._tray_menu = QMenu(window)
        self._open_action = QAction(localizer.text(StringKey.TRAY_OPEN), self)
        self._active_action = QAction(self)
        self._active_action.setEnabled(False)
        self._exit_action = QAction(localizer.text(StringKey.TRAY_EXIT), self)
        self._open_action.triggered.connect(self.open_window)
        self._exit_action.triggered.connect(self.request_exit)
        self._tray_menu.addAction(self._open_action)
        self._tray_menu.addAction(self._active_action)
        self._tray_menu.addSeparator()
        self._tray_menu.addAction(self._exit_action)
        self._tray.setContextMenu(self._tray_menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.messageClicked.connect(self._open_notification_target)
        self._presentation.downloads.state_changed.connect(self._update_active_count)
        self._presentation.bridge.application_event.connect(
            self._notify_for_event, Qt.ConnectionType.QueuedConnection
        )
        self._window.set_close_request_handler(self.request_exit)
        self._update_active_count()

    @property
    def tray_available(self) -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    @property
    def is_shutting_down(self) -> bool:
        return self._shutdown_started

    def request_exit(self) -> bool:
        """Handle user exit.  Returning false keeps Qt from closing prematurely."""

        assert_ui_thread(self)
        if self._shutdown_started:
            return False
        if self._presentation.downloads.state.summary.active > 0:
            self._ask_about_active_downloads()
        else:
            self._begin_shutdown()
        return False

    def open_window(self) -> None:
        assert_ui_thread(self)
        self._window.showNormal()
        self._window.raise_()
        self._window.activateWindow()

    def _ask_about_active_downloads(self) -> None:
        dialog = QMessageBox(self._window)
        dialog.setWindowTitle(self._localizer.text(StringKey.CLOSE_ACTIVE_TITLE))
        dialog.setText(self._localizer.text(StringKey.CLOSE_ACTIVE_BODY))
        if self.tray_available:
            tray = dialog.addButton(
                self._localizer.text(StringKey.CONTINUE_IN_TRAY), QMessageBox.ButtonRole.AcceptRole
            )
        else:
            tray = None
        stop = dialog.addButton(
            self._localizer.text(StringKey.STOP_AND_EXIT), QMessageBox.ButtonRole.DestructiveRole
        )
        dialog.addButton(
            self._localizer.text(StringKey.KEEP_CURRENT), QMessageBox.ButtonRole.RejectRole
        )
        dialog.exec()
        if tray is not None and dialog.clickedButton() is tray:
            self._move_to_tray()
        elif dialog.clickedButton() is stop:
            self._begin_shutdown()

    def _begin_shutdown(self) -> None:
        if self._shutdown_started:
            return
        self._shutdown_started = True
        self._presentation.close()
        self._window.setEnabled(False)
        self._window.statusBar().showMessage(self._localizer.text(StringKey.SHUTTING_DOWN))
        worker = _ShutdownThread(self._shutdown)
        worker.completed.connect(self._handle_shutdown_result)
        worker.finished.connect(worker.deleteLater)
        self._shutdown_thread = worker
        worker.start()

    def _handle_shutdown_result(self, result: object) -> None:
        assert_ui_thread(self)
        self.shutdown_completed.emit(result)
        if isinstance(result, ShutdownReport) and result.clean:
            self._tray.hide()
            self._window.close_after_shutdown()
            self._application.quit()
            return
        self._window.setEnabled(True)
        self.open_window()
        dialog = QMessageBox(self._window)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle(self._localizer.text(StringKey.SHUTDOWN_TIMEOUT_TITLE))
        dialog.setText(self._localizer.text(StringKey.SHUTDOWN_TIMEOUT_BODY))
        open_logs = dialog.addButton(
            self._localizer.text(StringKey.OPEN_LOGS), QMessageBox.ButtonRole.ActionRole
        )
        open_logs.clicked.connect(self._open_logs)
        dialog.addButton(
            self._localizer.text(StringKey.KEEP_CURRENT), QMessageBox.ButtonRole.RejectRole
        )
        dialog.open()

    def _move_to_tray(self) -> None:
        if not self.tray_available:
            return
        self._tray.show()
        self._window.hide()

    def _update_active_count(self, *_ignored: object) -> None:
        active = self._presentation.downloads.state.summary.active
        self._active_action.setText(
            self._localizer.text(StringKey.TRAY_ACTIVE_COUNT).format(count=active)
        )

    def _notify_for_event(self, event: ApplicationEvent) -> None:
        assert_ui_thread(self)
        if not self.tray_available or not isinstance(event, (OutputReady, TaskFailed)):
            return
        self._notification_task_id = str(event.task_id)
        title = self._localizer.text(
            StringKey.NOTIFICATION_COMPLETED_TITLE
            if isinstance(event, OutputReady)
            else StringKey.NOTIFICATION_FAILED_TITLE
        )
        self._tray.show()
        self._tray.showMessage(title, self._localizer.text(StringKey.APP_NAME))

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self.open_window()

    def _open_notification_target(self) -> None:
        if self._notification_task_id is None:
            return
        self.open_window()
        self._window.navigate(NavigationDestination.DOWNLOADS)
        self._presentation.downloads.select_task(self._notification_task_id)

    def _tray_icon(self) -> QIcon:
        icon = self._window.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        return icon
