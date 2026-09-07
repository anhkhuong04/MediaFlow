"""Safe, user-copyable diagnostics for task failures.

This module deliberately consumes the application read model rather than engine
payloads.  It is therefore safe to expose through the desktop UI and clipboard.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QWidget,
)

from mediaflow.application import TaskDetailsView
from mediaflow.presentation.strings import Localizer, StringKey


@dataclass(frozen=True, slots=True)
class DiagnosticDetails:
    """Redacted, stable fields suitable for an error details dialog."""

    task_id: str
    source: str
    stage: str
    message_key: str
    technical_detail: str
    timestamp: str

    def as_text(self, localizer: Localizer) -> str:
        fields = (
            (StringKey.DIAGNOSTICS_TASK_ID, self.task_id),
            (StringKey.DIAGNOSTICS_SOURCE, self.source),
            (StringKey.DIAGNOSTICS_STAGE, self.stage),
            (StringKey.DIAGNOSTICS_MESSAGE_KEY, self.message_key),
            (StringKey.DIAGNOSTICS_TECHNICAL_DETAIL, self.technical_detail),
            (StringKey.DIAGNOSTICS_TIMESTAMP, self.timestamp),
        )
        return "\n".join(f"{localizer.text(key)}: {value}" for key, value in fields)


def details_for_task(detail: TaskDetailsView) -> DiagnosticDetails:
    """Project a task read model without leaking a URL query, path, or raw error."""

    failure = detail.item.failure
    stage = (
        detail.item.progress.stage if detail.item.progress is not None else detail.item.status.value
    )
    return DiagnosticDetails(
        task_id=detail.item.task_id,
        source=redact_source(detail.source_url),
        stage=stage,
        message_key=failure.title_key if failure is not None else "error.unknown",
        technical_detail=_safe_code(failure.technical_code if failure is not None else "unknown"),
        timestamp=detail.item.updated_at.isoformat(),
    )


def redact_source(source_url: str) -> str:
    """Retain only a useful origin/path; queries often carry credentials or tokens."""

    try:
        parts = urlsplit(source_url)
        host = parts.hostname
        port = parts.port
    except ValueError:
        return "[redacted source]"
    if not parts.scheme or host is None:
        return "[redacted source]"
    safe_host = f"[{host}]" if ":" in host else host
    netloc = f"{safe_host}:{port}" if port is not None else safe_host
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def _safe_code(value: str) -> str:
    return "".join(character for character in value if character.isalnum() or character in "._-")[
        :120
    ]


class ErrorDetailsDialog(QDialog):
    """Present and copy the redacted details only after an explicit user action."""

    def __init__(
        self, details: DiagnosticDetails, localizer: Localizer, parent: QWidget | None
    ) -> None:
        super().__init__(parent)
        self._details = details
        self._localizer = localizer
        self.setWindowTitle(localizer.text(StringKey.ERROR_DETAILS_TITLE))
        form = QFormLayout(self)
        for key, value in (
            (StringKey.DIAGNOSTICS_TASK_ID, details.task_id),
            (StringKey.DIAGNOSTICS_SOURCE, details.source),
            (StringKey.DIAGNOSTICS_STAGE, details.stage),
            (StringKey.DIAGNOSTICS_MESSAGE_KEY, details.message_key),
            (StringKey.DIAGNOSTICS_TECHNICAL_DETAIL, details.technical_detail),
            (StringKey.DIAGNOSTICS_TIMESTAMP, details.timestamp),
        ):
            label = QLabel(value, self)
            label.setTextInteractionFlags(label.textInteractionFlags())
            label.setWordWrap(True)
            form.addRow(f"{localizer.text(key)}:", label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        copy_button = buttons.addButton(
            localizer.text(StringKey.COPY_DIAGNOSTICS), QDialogButtonBox.ButtonRole.ActionRole
        )
        copy_button.clicked.connect(self.copy_diagnostics)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def copy_diagnostics(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._details.as_text(self._localizer))
