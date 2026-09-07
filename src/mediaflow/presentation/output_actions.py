"""Qt-owned, capability-gated output actions without shell command construction."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


class OutputLauncher(Protocol):
    """Presentation boundary for opening an already verified output location."""

    def open_file(self, output_path: str, *, allowed: bool) -> bool: ...

    def open_folder(self, output_path: str, *, allowed: bool) -> bool: ...


class QtOutputLauncher:
    """Use Qt local-file URLs; never interpolate an untrusted path into a shell command."""

    def open_file(self, output_path: str, *, allowed: bool) -> bool:
        return self._open(output_path, allowed=allowed)

    def open_folder(self, output_path: str, *, allowed: bool) -> bool:
        return self._open(str(Path(output_path).parent), allowed=allowed)

    @staticmethod
    def _open(path: str, *, allowed: bool) -> bool:
        if not allowed or not path:
            return False
        return QDesktopServices.openUrl(QUrl.fromLocalFile(path))
