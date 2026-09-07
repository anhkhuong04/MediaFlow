"""Incremental Downloads state center backed only by C8 read models."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFocusEvent, QResizeEvent
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from mediaflow.application import DownloadItemView, DownloadStatus, ProgressView, TaskDetailsView
from mediaflow.presentation.accessibility import complete_control_accessibility
from mediaflow.presentation.controllers import DownloadsController, DownloadsState, TaskAction
from mediaflow.presentation.design import TOKENS
from mediaflow.presentation.diagnostics import ErrorDetailsDialog, details_for_task
from mediaflow.presentation.output_actions import OutputLauncher, QtOutputLauncher
from mediaflow.presentation.strings import Localizer, StringKey
from mediaflow.presentation.window import assert_ui_thread


class DownloadsPage(QScrollArea):
    """Render authoritative downloads incrementally, keyed by stable task ID."""

    def __init__(
        self,
        controller: DownloadsController,
        *,
        localizer: Localizer | None = None,
        output_launcher: OutputLauncher | None = None,
    ) -> None:
        super().__init__()
        self._controller = controller
        self._localizer = localizer or Localizer()
        self._output_launcher = output_launcher or QtOutputLauncher()
        self._cards: dict[str, DownloadCard] = {}
        self._pending_details: set[str] = set()
        self._detail_dialogs: dict[str, ErrorDetailsDialog] = {}
        self._last_status_by_task_id: dict[str, DownloadStatus] = {}
        self.setObjectName("screenScroll")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget(self)
        self.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(
            TOKENS.spacing.section,
            TOKENS.spacing.section,
            TOKENS.spacing.section,
            TOKENS.spacing.section,
        )
        layout.setSpacing(TOKENS.spacing.standard)
        title = QLabel(self._text(StringKey.DOWNLOADS_TITLE), content)
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        self.summary = QLabel(content)
        self.summary.setObjectName("secondaryText")
        layout.addWidget(self.summary)
        self.status_announcement = QLabel(content)
        self.status_announcement.setObjectName("screenReaderStatus")
        self.status_announcement.setWordWrap(True)
        self.status_announcement.setVisible(False)
        layout.addWidget(self.status_announcement)
        self._sections = {
            "active": _TaskSection(
                self._text(StringKey.ACTIVE), self._text(StringKey.NO_ACTIVE), content
            ),
            "queued": _TaskSection(
                self._text(StringKey.QUEUED_SECTION), self._text(StringKey.NO_QUEUED), content
            ),
            "recent": _TaskSection(
                self._text(StringKey.RECENTLY_COMPLETED), self._text(StringKey.NO_RECENT), content
            ),
        }
        for section in self._sections.values():
            layout.addWidget(section)
        layout.addStretch(1)
        self._controller.state_changed.connect(self.render_state)
        complete_control_accessibility(self)
        self.render_state(self._controller.state)

    def render_state(self, state: DownloadsState) -> None:
        """Update cards by stable ID; existing card widgets retain their own focus."""

        assert_ui_thread(self)
        items_by_section: dict[str, list[DownloadItemView]] = {
            "active": [],
            "queued": [],
            "recent": [],
        }
        for item in state.items:
            items_by_section[_section_for(item)].append(item)
            card = self._cards.get(item.task_id)
            if card is None:
                card = DownloadCard(
                    item, self._controller, self._localizer, self._output_launcher, self
                )
                card.focused.connect(self._controller.select_task)
                card.details_requested.connect(self._show_details)
                self._cards[item.task_id] = card
            else:
                card.update_item(item)
            card.set_selected(item.task_id == state.selected_task_id)
            self._announce_terminal_transition(item)

        current_ids = {item.task_id for item in state.items}
        for task_id, card in tuple(self._cards.items()):
            if task_id not in current_ids:
                card.setParent(None)
                card.deleteLater()
                del self._cards[task_id]
        for name, items in items_by_section.items():
            self._sections[name].set_cards([self._cards[item.task_id] for item in items])
        summary = state.summary
        self.summary.setText(
            f"{summary.active} {self._text(StringKey.ACTIVE).lower()} · "
            f"{summary.queued} {self._text(StringKey.QUEUED_SECTION).lower()} · "
            f"{summary.completed} {self._text(StringKey.STATUS_COMPLETED).lower()} · "
            f"{summary.failed} {self._text(StringKey.STATUS_FAILED).lower()}"
        )

        details_by_id = {detail.item.task_id: detail for detail in state.details}
        for task_id in tuple(self._pending_details):
            detail = details_by_id.get(task_id)
            if detail is not None:
                self._pending_details.remove(task_id)
                self._present_details(detail)

    def _show_details(self, task_id: str) -> None:
        detail = self._controller.details_for(task_id)
        if detail is not None:
            self._present_details(detail)
            return
        self._pending_details.add(task_id)
        self._controller.load_details(task_id)

    def _present_details(self, detail: TaskDetailsView) -> None:
        task_id = detail.item.task_id
        existing = self._detail_dialogs.get(task_id)
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return
        dialog = ErrorDetailsDialog(details_for_task(detail), self._localizer, self)
        dialog.finished.connect(
            lambda _result, selected=task_id: self._detail_dialogs.pop(selected, None)
        )
        self._detail_dialogs[task_id] = dialog
        dialog.open()

    def _text(self, key: StringKey) -> str:
        return self._localizer.text(key)

    def _announce_terminal_transition(self, item: DownloadItemView) -> None:
        previous = self._last_status_by_task_id.get(item.task_id)
        self._last_status_by_task_id[item.task_id] = item.status
        if (
            previous is None
            or previous is item.status
            or item.status
            not in {
                DownloadStatus.COMPLETED,
                DownloadStatus.FAILED,
                DownloadStatus.CANCELLED,
                DownloadStatus.INTERRUPTED,
            }
        ):
            return
        message = self._text(StringKey.STATUS_ANNOUNCEMENT).format(
            title=item.title, status=_status_text(item.status, self._localizer)
        )
        self.status_announcement.setText(message)
        self.status_announcement.setAccessibleName(message)
        self.status_announcement.setAccessibleDescription(message)
        self.status_announcement.setVisible(True)


class _TaskSection(QFrame):
    def __init__(self, title: str, empty_text: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("screenCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            TOKENS.spacing.standard,
            TOKENS.spacing.standard,
            TOKENS.spacing.standard,
            TOKENS.spacing.standard,
        )
        layout.setSpacing(TOKENS.spacing.small)
        heading = QLabel(title, self)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        self.empty = QLabel(empty_text, self)
        self.empty.setObjectName("helperText")
        layout.addWidget(self.empty)
        self.cards_layout = QVBoxLayout()
        self.cards_layout.setSpacing(TOKENS.spacing.small)
        layout.addLayout(self.cards_layout)

    def set_cards(self, cards: list[DownloadCard]) -> None:
        while self.cards_layout.count():
            self.cards_layout.takeAt(0)
        self.empty.setVisible(not cards)
        for card in cards:
            self.cards_layout.addWidget(card)


class DownloadCard(QFrame):
    """One card whose update path never depends on a mutable row index."""

    focused = Signal(str)
    details_requested = Signal(str)

    def __init__(
        self,
        item: DownloadItemView,
        controller: DownloadsController,
        localizer: Localizer,
        output_launcher: OutputLauncher,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self._item = item
        self._controller = controller
        self._localizer = localizer
        self._output_launcher = output_launcher
        self.setObjectName("downloadCard")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._compact_actions = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            TOKENS.spacing.compact,
            TOKENS.spacing.compact,
            TOKENS.spacing.compact,
            TOKENS.spacing.compact,
        )
        layout.setSpacing(TOKENS.spacing.small)
        self.title = QLabel(self)
        self.title.setWordWrap(True)
        self.title.setMaximumHeight(42)
        layout.addWidget(self.title)
        self.details = QLabel(self)
        self.details.setObjectName("secondaryText")
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        self.stage = QLabel(self)
        layout.addWidget(self.stage)
        self.progress = QProgressBar(self)
        self.progress.setTextVisible(True)
        layout.addWidget(self.progress)
        self.progress_details = QLabel(self)
        self.progress_details.setObjectName("helperText")
        layout.addWidget(self.progress_details)
        self.failure = QLabel(self)
        self.failure.setObjectName("errorText")
        self.failure.setWordWrap(True)
        layout.addWidget(self.failure)
        self.actions_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.actions_layout.setSpacing(TOKENS.spacing.small)
        layout.addLayout(self.actions_layout)
        self._buttons = {
            action: QPushButton(self._text(key), self)
            for action, key in (
                (TaskAction.CANCEL, StringKey.CANCEL),
                (TaskAction.RETRY, StringKey.RETRY),
                (TaskAction.RESUME, StringKey.RESUME),
                (TaskAction.RESTART, StringKey.RESTART),
                (TaskAction.RETRY_PROCESSING, StringKey.RETRY_PROCESSING),
            )
        }
        for action, button in self._buttons.items():
            button.clicked.connect(lambda _checked=False, selected=action: self._invoke(selected))
            self.actions_layout.addWidget(button)
        self.open_file = QPushButton(self._text(StringKey.OPEN_FILE), self)
        self.open_file.clicked.connect(self._open_file)
        self.actions_layout.addWidget(self.open_file)
        self.open_folder = QPushButton(self._text(StringKey.OPEN_FOLDER), self)
        self.open_folder.clicked.connect(self._open_folder)
        self.actions_layout.addWidget(self.open_folder)
        self.details_button = QPushButton(self._text(StringKey.DETAILS), self)
        self.details_button.clicked.connect(lambda: self.details_requested.emit(self._item.task_id))
        self.actions_layout.addWidget(self.details_button)
        self.actions_layout.addStretch(1)
        complete_control_accessibility(self)
        self.update_item(item)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        compact = self.width() < 620
        if compact != self._compact_actions:
            self._compact_actions = compact
            self.actions_layout.setDirection(
                QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight
            )

    def focusInEvent(self, event: QFocusEvent) -> None:
        super().focusInEvent(event)
        self.focused.emit(self._item.task_id)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selectedTask", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def update_item(self, item: DownloadItemView) -> None:
        self._item = item
        self.title.setText(item.title)
        self.title.setToolTip(item.title)
        self.details.setText(f"{item.quality} · {item.container}")
        self.stage.setText(_status_text(item.status, self._localizer))
        self._set_progress(item.progress, item.status)
        self.failure.setVisible(item.failure is not None)
        if item.failure is not None:
            self.failure.setText(
                f"{self._text(StringKey.ERROR_GENERIC_TITLE)} — "
                f"{self._text(StringKey.ERROR_GENERIC_BODY)}"
            )
        for action, button in self._buttons.items():
            available = {
                TaskAction.CANCEL: item.actions.can_cancel,
                TaskAction.RETRY: item.actions.can_retry,
                TaskAction.RESUME: item.actions.can_resume,
                TaskAction.RESTART: item.actions.can_restart,
                TaskAction.RETRY_PROCESSING: item.actions.can_retry_processing,
            }[action]
            button.setVisible(available)
            button.setEnabled(available and not self._action_busy(action))
        self.open_file.setVisible(item.actions.can_open_output)
        self.open_folder.setVisible(item.actions.can_open_output)
        self.details_button.setVisible(item.failure is not None)

    def _set_progress(self, progress: ProgressView | None, status: DownloadStatus) -> None:
        if status is DownloadStatus.PROCESSING and (progress is None or progress.fraction is None):
            self.progress.setRange(0, 0)
            self.progress.setVisible(True)
            self.progress_details.setText(self._text(StringKey.STATUS_PROCESSING))
            return
        if progress is None:
            self.progress.setVisible(False)
            self.progress_details.setText("")
            return
        self.progress.setVisible(True)
        if progress.fraction is None:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(round(progress.fraction * 100))
        fields = [
            _bytes_text(progress.downloaded_bytes, self._localizer),
            _bytes_text(progress.total_bytes, self._localizer),
            _speed_text(progress.speed_bytes_per_second, self._localizer),
            _eta_text(progress.eta_seconds, self._localizer),
        ]
        self.progress_details.setText(" · ".join(fields))

    def _invoke(self, action: TaskAction) -> None:
        if action is TaskAction.CANCEL and not self._confirm_cancel():
            return
        self._controller.invoke_action(self._item.task_id, action)

    def _confirm_cancel(self) -> bool:
        dialog = QMessageBox(self)
        dialog.setWindowTitle(self._text(StringKey.CANCEL_DOWNLOAD_TITLE))
        dialog.setText(self._text(StringKey.CANCEL_DOWNLOAD_BODY))
        confirm = dialog.addButton(
            self._text(StringKey.CANCEL_DOWNLOAD_CONFIRM), QMessageBox.ButtonRole.DestructiveRole
        )
        dialog.addButton(self._text(StringKey.KEEP_CURRENT), QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        return dialog.clickedButton() is confirm

    def _open_file(self) -> None:
        if self._item.actions.can_open_output and self._item.output_path:
            self._output_launcher.open_file(
                self._item.output_path, allowed=self._item.actions.can_open_output
            )

    def _open_folder(self) -> None:
        if self._item.actions.can_open_output and self._item.output_path:
            self._output_launcher.open_folder(
                self._item.output_path, allowed=self._item.actions.can_open_output
            )

    def _action_busy(self, action: TaskAction) -> bool:
        return any(
            state.task_id == self._item.task_id and state.action is action and state.state.is_busy
            for state in self._controller.state.action_states
        )

    def _text(self, key: StringKey) -> str:
        return self._localizer.text(key)


def _section_for(item: DownloadItemView) -> str:
    if item.status is DownloadStatus.WAITING:
        return "queued"
    if item.status in {DownloadStatus.COMPLETED, DownloadStatus.FAILED, DownloadStatus.CANCELLED}:
        return "recent"
    return "active"


def _status_text(status: DownloadStatus, localizer: Localizer) -> str:
    return localizer.text(
        {
            DownloadStatus.WAITING: StringKey.STATUS_WAITING,
            DownloadStatus.DOWNLOADING: StringKey.STATUS_DOWNLOADING,
            DownloadStatus.PROCESSING: StringKey.STATUS_PROCESSING,
            DownloadStatus.PAUSED: StringKey.STATUS_PAUSED,
            DownloadStatus.INTERRUPTED: StringKey.STATUS_INTERRUPTED,
            DownloadStatus.COMPLETED: StringKey.STATUS_COMPLETED,
            DownloadStatus.FAILED: StringKey.STATUS_FAILED,
            DownloadStatus.CANCELLED: StringKey.STATUS_CANCELLED,
        }[status]
    )


def _bytes_text(value: int | None, localizer: Localizer) -> str:
    if value is None:
        return localizer.text(StringKey.UNKNOWN_VALUE)
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(value)
    for unit in units[:-1]:
        if amount < 1024:
            return f"{amount:.0f} {unit}"
        amount /= 1024
    return f"{amount:.1f} {units[-1]}"


def _speed_text(value: float | None, localizer: Localizer) -> str:
    return (
        _bytes_text(round(value), localizer) + "/s"
        if value is not None
        else localizer.text(StringKey.UNKNOWN_VALUE)
    )


def _eta_text(value: float | None, localizer: Localizer) -> str:
    if value is None:
        return localizer.text(StringKey.UNKNOWN_VALUE)
    seconds = max(0, round(value))
    minutes, seconds = divmod(seconds, 60)
    return localizer.text(StringKey.ETA).format(value=f"{minutes}:{seconds:02d}")
