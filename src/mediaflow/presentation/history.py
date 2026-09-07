"""Terminal-download history with explicit output actions and deletion confirmation."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QCheckBox,
    QFrame,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from mediaflow.application import HistoryItemView, TaskDetailsView
from mediaflow.presentation.accessibility import complete_control_accessibility
from mediaflow.presentation.controllers import HistoryController, HistoryState
from mediaflow.presentation.design import TOKENS
from mediaflow.presentation.downloads import _status_text
from mediaflow.presentation.output_actions import OutputLauncher, QtOutputLauncher
from mediaflow.presentation.strings import Localizer, StringKey
from mediaflow.presentation.window import assert_ui_thread


class HistoryPage(QScrollArea):
    """Render only terminal projection entries; active work remains in Downloads."""

    download_again_requested = Signal(str)

    def __init__(
        self,
        controller: HistoryController,
        *,
        localizer: Localizer | None = None,
        output_launcher: OutputLauncher | None = None,
    ) -> None:
        super().__init__()
        self._controller = controller
        self._localizer = localizer or Localizer()
        self._output_launcher = output_launcher or QtOutputLauncher()
        self._cards: dict[str, HistoryCard] = {}
        self._pending_intents: dict[str, str] = {}
        self._shown_removal_result: tuple[str, bool] | None = None
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
        title = QLabel(self._text(StringKey.HISTORY_TITLE), content)
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        self.empty = QLabel(self._text(StringKey.HISTORY_EMPTY), content)
        self.empty.setObjectName("helperText")
        layout.addWidget(self.empty)
        self.cards_layout = QVBoxLayout()
        self.cards_layout.setSpacing(TOKENS.spacing.small)
        layout.addLayout(self.cards_layout)
        self.notice = QLabel(content)
        self.notice.setObjectName("errorText")
        self.notice.setVisible(False)
        layout.addWidget(self.notice)
        layout.addStretch(1)
        self._controller.state_changed.connect(self.render_state)
        complete_control_accessibility(self)
        self.render_state(self._controller.state)

    def render_state(self, state: HistoryState) -> None:
        assert_ui_thread(self)
        details_by_id = {detail.item.task_id: detail for detail in state.details}
        for item in state.items:
            card = self._cards.get(item.task_id)
            if card is None:
                card = HistoryCard(item, self._localizer, self._output_launcher, self)
                card.download_again.connect(self._download_again)
                card.copy_source.connect(self._copy_source)
                card.remove_requested.connect(self._remove)
                self._cards[item.task_id] = card
            else:
                card.update_item(item)
            detail = details_by_id.get(item.task_id)
            if detail is not None:
                card.apply_detail(detail)
                intent = self._pending_intents.pop(item.task_id, None)
                if intent == "download_again":
                    self.download_again_requested.emit(detail.source_url)
                elif intent == "copy_source":
                    clipboard = QApplication.clipboard()
                    if clipboard is not None:
                        clipboard.setText(detail.source_url)

        visible_ids = {item.task_id for item in state.items}
        for task_id, card in tuple(self._cards.items()):
            if task_id not in visible_ids:
                card.setParent(None)
                card.deleteLater()
                del self._cards[task_id]
        while self.cards_layout.count():
            self.cards_layout.takeAt(0)
        for item in state.items:
            self.cards_layout.addWidget(self._cards[item.task_id])
        self.empty.setVisible(not state.items)
        removal = state.removal_result
        if removal is not None:
            result_key = (removal.task_id, removal.output_delete_requested)
            if result_key != self._shown_removal_result:
                self._shown_removal_result = result_key
                failed = removal.output_delete_requested and not removal.output_deleted
                self.notice.setText(self._text(StringKey.OUTPUT_DELETE_RESULT))
                self.notice.setVisible(failed)

    def _download_again(self, task_id: str) -> None:
        self._request_detail(task_id, "download_again")

    def _copy_source(self, task_id: str) -> None:
        self._request_detail(task_id, "copy_source")

    def _request_detail(self, task_id: str, intent: str) -> None:
        detail = self._controller.details_for(task_id)
        if detail is not None:
            if intent == "download_again":
                self.download_again_requested.emit(detail.source_url)
            else:
                clipboard = QApplication.clipboard()
                if clipboard is not None:
                    clipboard.setText(detail.source_url)
            return
        self._pending_intents[task_id] = intent
        self._controller.load_details(task_id)

    def _remove(self, task_id: str, delete_output: bool) -> None:
        self._controller.remove(task_id, delete_output=delete_output)

    def _text(self, key: StringKey) -> str:
        return self._localizer.text(key)


class HistoryCard(QFrame):
    """One terminal entry with capabilities, never path-string inferred actions."""

    download_again = Signal(str)
    copy_source = Signal(str)
    remove_requested = Signal(str, bool)

    def __init__(
        self,
        item: HistoryItemView,
        localizer: Localizer,
        output_launcher: OutputLauncher,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self._item = item
        self._localizer = localizer
        self._output_launcher = output_launcher
        self.setObjectName("downloadCard")
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
        layout.addWidget(self.details)
        self.output_status = QLabel(self)
        self.output_status.setObjectName("helperText")
        layout.addWidget(self.output_status)
        actions = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.actions_layout = actions
        actions.setSpacing(TOKENS.spacing.small)
        layout.addLayout(actions)
        self.open_file = QPushButton(self._text(StringKey.OPEN_FILE), self)
        self.open_file.clicked.connect(self._open_file)
        actions.addWidget(self.open_file)
        self.open_folder = QPushButton(self._text(StringKey.OPEN_FOLDER), self)
        self.open_folder.clicked.connect(self._open_folder)
        actions.addWidget(self.open_folder)
        self.download_button = QPushButton(self._text(StringKey.DOWNLOAD_AGAIN), self)
        self.download_button.clicked.connect(lambda: self.download_again.emit(self._item.task_id))
        actions.addWidget(self.download_button)
        self.copy_button = QPushButton(self._text(StringKey.COPY_SOURCE_URL), self)
        self.copy_button.clicked.connect(lambda: self.copy_source.emit(self._item.task_id))
        actions.addWidget(self.copy_button)
        self.remove_button = QPushButton(self._text(StringKey.REMOVE_HISTORY), self)
        self.remove_button.clicked.connect(self._confirm_remove)
        actions.addWidget(self.remove_button)
        actions.addStretch(1)
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

    def update_item(self, item: HistoryItemView) -> None:
        self._item = item
        self.title.setText(item.title)
        self.title.setToolTip(item.title)
        date = item.finished_at.astimezone().strftime("%Y-%m-%d %H:%M")
        self.details.setText(
            " / ".join(
                (_status_text(item.status, self._localizer), item.quality, item.container, date)
            )
        )
        available = item.actions.can_open_output
        self.open_file.setVisible(available)
        self.open_folder.setVisible(available)
        self.output_status.setText(
            ""
            if available or item.output_path is None
            else self._text(StringKey.OUTPUT_UNAVAILABLE)
        )
        self.output_status.setVisible(not available and item.output_path is not None)

    def apply_detail(self, detail: TaskDetailsView) -> None:
        self.download_button.setEnabled(bool(detail.source_url))
        self.copy_button.setEnabled(bool(detail.source_url))

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

    def _confirm_remove(self) -> None:
        dialog = QMessageBox(self)
        dialog.setWindowTitle(self._text(StringKey.REMOVE_HISTORY_TITLE))
        dialog.setText(self._text(StringKey.REMOVE_HISTORY_BODY))
        delete_output = QCheckBox(self._text(StringKey.DELETE_OUTPUT), dialog)
        delete_output.setChecked(False)
        delete_output.setEnabled(self._item.actions.can_open_output)
        dialog.setCheckBox(delete_output)
        confirm = dialog.addButton(
            self._text(StringKey.REMOVE_HISTORY_CONFIRM), QMessageBox.ButtonRole.DestructiveRole
        )
        dialog.addButton(self._text(StringKey.KEEP_CURRENT), QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        if dialog.clickedButton() is confirm:
            self.remove_requested.emit(self._item.task_id, delete_output.isChecked())

    def _text(self, key: StringKey) -> str:
        return self._localizer.text(key)
