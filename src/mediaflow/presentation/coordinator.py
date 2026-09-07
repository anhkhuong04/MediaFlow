"""Composition and lifetime owner for Qt presentation state, bridge, and controllers."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt

from mediaflow.application import ApplicationEvent
from mediaflow.presentation.bridge import (
    CommandCompletion,
    PresentationCommandRunner,
    QtEventBridge,
)
from mediaflow.presentation.contracts import PresentationFacade
from mediaflow.presentation.controllers import (
    DownloadsController,
    HistoryController,
    HomeController,
    SettingsController,
)
from mediaflow.presentation.window import assert_ui_thread


class PresentationCoordinator(QObject):
    """Own presentation subscriptions and command work for one desktop runtime session."""

    def __init__(self, facade: PresentationFacade) -> None:
        super().__init__()
        assert_ui_thread(self)
        self.bridge = QtEventBridge(facade)
        self.runner = PresentationCommandRunner(self.bridge)
        self.home = HomeController(facade, self.bridge, self.runner)
        self.downloads = DownloadsController(facade, self.runner)
        self.history = HistoryController(facade, self.runner)
        self.settings = SettingsController(facade, self.runner)
        self._closed = False
        self.bridge.application_event.connect(self._route_event, Qt.ConnectionType.QueuedConnection)
        self.bridge.command_completed.connect(
            self._route_completion, Qt.ConnectionType.QueuedConnection
        )

    @property
    def is_closed(self) -> bool:
        return self._closed

    def start(self) -> None:
        """Subscribe once and initialize typed projections without blocking the window."""

        assert_ui_thread(self)
        if self._closed:
            raise RuntimeError("A closed presentation coordinator cannot be restarted")
        self.bridge.start()
        self.downloads.refresh()
        self.history.refresh()
        self.settings.load()
        self.settings.load_dependencies()

    def close(self) -> None:
        """Stop delivery before joining presentation work and before core infrastructure stops."""

        assert_ui_thread(self)
        if self._closed:
            return
        self._closed = True
        self.bridge.close()
        self.runner.close()

    def _route_event(self, event: ApplicationEvent) -> None:
        assert_ui_thread(self)
        if self._closed:
            return
        self.downloads.handle_event(event)
        self.history.handle_event(event)

    def _route_completion(self, completion: CommandCompletion) -> None:
        assert_ui_thread(self)
        if self._closed:
            return
        self.home.handle_completion(completion)
        self.downloads.handle_completion(completion)
        self.history.handle_completion(completion)
        self.settings.handle_completion(completion)
