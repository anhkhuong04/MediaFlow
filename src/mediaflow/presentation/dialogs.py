"""Reusable dialogs for typed backend conditions surfaced in later workflow slices."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

from mediaflow.application import ConflictPolicy, DiskSpaceEstimate
from mediaflow.presentation.accessibility import complete_control_accessibility
from mediaflow.presentation.strings import Localizer, StringKey


class ConflictDialog(QDialog):
    """Require an explicit destructive Replace choice; Rename is the safe default."""

    def __init__(self, localizer: Localizer, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.decision = ConflictPolicy.RENAME
        self.setWindowTitle(localizer.text(StringKey.CONFLICT_TITLE))
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(localizer.text(StringKey.CONFLICT_BODY), self))
        buttons = QDialogButtonBox(self)
        rename = buttons.addButton(
            localizer.text(StringKey.RENAME), QDialogButtonBox.ButtonRole.AcceptRole
        )
        skip = buttons.addButton(
            localizer.text(StringKey.SKIP), QDialogButtonBox.ButtonRole.RejectRole
        )
        replace = buttons.addButton(
            localizer.text(StringKey.REPLACE), QDialogButtonBox.ButtonRole.DestructiveRole
        )
        rename.clicked.connect(lambda: self._choose(ConflictPolicy.RENAME))
        skip.clicked.connect(lambda: self._choose(ConflictPolicy.SKIP))
        replace.clicked.connect(lambda: self._choose(ConflictPolicy.REPLACE))
        layout.addWidget(buttons)
        complete_control_accessibility(self)

    def _choose(self, policy: ConflictPolicy) -> None:
        self.decision = policy
        self.accept()


class DiskSpaceWarningDialog(QDialog):
    """Display a point-in-time estimate and let the caller request a safe folder picker."""

    choose_folder_requested = Signal()

    def __init__(
        self, estimate: DiskSpaceEstimate, localizer: Localizer, parent: QWidget | None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(localizer.text(StringKey.DISK_SPACE_TITLE))
        layout = QVBoxLayout(self)
        body = localizer.text(StringKey.DISK_SPACE_BODY).format(
            required=_bytes_text(estimate.required_bytes),
            available=_bytes_text(estimate.available_bytes),
        )
        message = QLabel(body, self)
        message.setWordWrap(True)
        layout.addWidget(message)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        choose = buttons.addButton(
            localizer.text(StringKey.CHOOSE_ANOTHER_FOLDER), QDialogButtonBox.ButtonRole.ActionRole
        )
        choose.clicked.connect(self.choose_folder_requested)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        complete_control_accessibility(self)


def _bytes_text(value: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(value)
    for unit in units[:-1]:
        if amount < 1024:
            return f"{amount:.0f} {unit}"
        amount /= 1024
    return f"{amount:.1f} {units[-1]}"
