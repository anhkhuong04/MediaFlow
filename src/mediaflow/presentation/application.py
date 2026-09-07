"""Ownership boundary between the Qt process lifecycle and the core runtime."""

from dataclasses import dataclass, field

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from mediaflow.application import ShutdownReport
from mediaflow.bootstrap import BootstrapConfig, MediaFlowRuntime, build_runtime
from mediaflow.presentation.coordinator import PresentationCoordinator
from mediaflow.presentation.downloads import DownloadsPage
from mediaflow.presentation.history import HistoryPage
from mediaflow.presentation.home import HomePage
from mediaflow.presentation.shell import NavigationDestination
from mediaflow.presentation.window import MediaFlowWindow


@dataclass(slots=True)
class DesktopRuntime:
    """Own the window and core runtime for exactly one desktop process."""

    application: QApplication
    core_runtime: MediaFlowRuntime
    window: MediaFlowWindow
    presentation: PresentationCoordinator
    _shutdown_report: ShutdownReport | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.application.aboutToQuit.connect(self.shutdown)

    @property
    def is_shutdown(self) -> bool:
        return self._shutdown_report is not None

    def show(self) -> None:
        if self.is_shutdown:
            raise RuntimeError("Desktop runtime is already shut down")
        self.window.show()

    def shutdown(self) -> None:
        """Stop core work before hiding the owned top-level window.

        Qt can emit ``aboutToQuit`` and the entry point also calls this method in a
        ``finally`` block, so it deliberately has idempotent semantics.
        """

        if self.is_shutdown:
            return
        self.application.aboutToQuit.disconnect(self.shutdown)
        self.presentation.close()
        self._shutdown_report = self.core_runtime.shutdown()
        self.window.close()


def build_desktop_runtime(
    config: BootstrapConfig,
    *,
    application: QApplication,
    geometry_store: QSettings | None = None,
) -> DesktopRuntime:
    """Compose the existing core once and expose no infrastructure to widgets."""

    core_runtime = build_runtime(config)
    window = MediaFlowWindow(geometry_store=geometry_store)
    presentation = PresentationCoordinator(core_runtime.facade)
    home = HomePage(presentation.home)
    downloads = DownloadsPage(presentation.downloads)
    history = HistoryPage(presentation.history)
    window.replace_page(NavigationDestination.HOME, home)
    window.replace_page(NavigationDestination.DOWNLOADS, downloads)
    window.replace_page(NavigationDestination.HISTORY, history)
    home.queued.connect(lambda: window.navigate(NavigationDestination.DOWNLOADS))
    history.download_again_requested.connect(
        lambda source_url: _analyze_history_source(home, window, source_url)
    )
    presentation.settings.state_changed.connect(
        lambda state: (
            home.set_default_output_directory(state.settings.default_output_directory)
            if state.settings is not None
            else None
        )
    )
    window.closed.connect(presentation.close)
    presentation.start()
    return DesktopRuntime(
        application=application,
        core_runtime=core_runtime,
        window=window,
        presentation=presentation,
    )


def _analyze_history_source(home: HomePage, window: MediaFlowWindow, source_url: str) -> None:
    """Return to Home only when its controller accepts this explicit user intent."""

    if home.analyze_source(source_url):
        window.navigate(NavigationDestination.HOME)
