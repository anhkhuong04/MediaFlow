"""Desktop process entry point and operating-system-owned path selection."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, Qt
from PySide6.QtWidgets import QApplication

from mediaflow.bootstrap import BootstrapConfig
from mediaflow.presentation.application import build_desktop_runtime


def create_application(argv: Sequence[str] | None = None) -> QApplication:
    """Return the process QApplication, creating it only when one does not exist."""

    existing = QApplication.instance()
    if existing is not None:
        if not isinstance(existing, QApplication):
            raise RuntimeError("A non-widget Qt application already owns this process")
        return existing

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    application = QApplication(list(sys.argv if argv is None else argv))
    application.setOrganizationName("MediaFlow")
    application.setApplicationName("MediaFlow")
    return application


def default_bootstrap_config() -> BootstrapConfig:
    """Choose per-user Windows locations without hard-coding a machine path."""

    data_directory = _standard_location(QStandardPaths.StandardLocation.AppLocalDataLocation)
    downloads_directory = _standard_location(QStandardPaths.StandardLocation.DownloadLocation)
    return BootstrapConfig(
        data_directory=data_directory.resolve(),
        default_output_directory=downloads_directory.resolve(),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the desktop shell and always release the core runtime on exit."""

    application = create_application(argv)
    runtime = build_desktop_runtime(
        default_bootstrap_config(),
        application=application,
        geometry_store=QSettings(),
    )
    try:
        runtime.show()
        return application.exec()
    finally:
        runtime.shutdown()


def _standard_location(location: QStandardPaths.StandardLocation) -> Path:
    value = QStandardPaths.writableLocation(location)
    if not value:
        raise RuntimeError(f"Qt did not provide a writable standard location for {location.name}")
    return Path(value)
