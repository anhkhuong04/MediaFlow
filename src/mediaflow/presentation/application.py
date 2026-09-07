"""Ownership boundary between the Qt process lifecycle and the core runtime."""

from dataclasses import dataclass, field

from PySide6.QtWidgets import QApplication

from mediaflow.application import ShutdownReport
from mediaflow.bootstrap import BootstrapConfig, MediaFlowRuntime, build_runtime
from mediaflow.presentation.window import MediaFlowWindow


@dataclass(slots=True)
class DesktopRuntime:
    """Own the window and core runtime for exactly one desktop process."""

    application: QApplication
    core_runtime: MediaFlowRuntime
    window: MediaFlowWindow
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
        self._shutdown_report = self.core_runtime.shutdown()
        self.window.close()


def build_desktop_runtime(config: BootstrapConfig, *, application: QApplication) -> DesktopRuntime:
    """Compose the existing core once and expose no infrastructure to widgets."""

    return DesktopRuntime(
        application=application,
        core_runtime=build_runtime(config),
        window=MediaFlowWindow(),
    )
