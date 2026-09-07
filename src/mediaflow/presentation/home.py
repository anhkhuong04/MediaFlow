"""Home vertical slice: explicit URL analysis and typed queueing intent."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mediaflow.application import MediaConfigurationView, MediaKind, PresetOptionView
from mediaflow.presentation.controllers import HomeController, HomeState
from mediaflow.presentation.design import TOKENS
from mediaflow.presentation.strings import Localizer, StringKey
from mediaflow.presentation.window import assert_ui_thread


class HomePage(QScrollArea):
    """A state-complete Home screen that never owns a core facade or worker."""

    queued = Signal()

    def __init__(self, controller: HomeController, *, localizer: Localizer | None = None) -> None:
        super().__init__()
        self._controller = controller
        self._localizer = localizer or Localizer()
        self._configuration: MediaConfigurationView | None = None
        self._mode = MediaKind.VIDEO
        self._default_directory = ""
        self._location_was_edited = False
        self._is_dirty = False
        self._enqueue_was_busy = False

        self.setObjectName("screenScroll")
        self.setWidgetResizable(True)
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

        title = QLabel(self._text(StringKey.HOME_TITLE), content)
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(self._build_url_card(content))
        layout.addWidget(self._build_configuration_card(content))
        layout.addStretch(1)

        focus_url = QAction(self)
        focus_url.setShortcut(QKeySequence("Ctrl+L"))
        focus_url.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        focus_url.triggered.connect(self.url_input.setFocus)
        self.addAction(focus_url)
        self._controller.state_changed.connect(self.render_state)
        self._delayed_timer = QTimer(self)
        self._delayed_timer.setSingleShot(True)
        self._delayed_timer.setInterval(2_000)
        self._delayed_timer.timeout.connect(self._show_delayed_copy)
        self.render_state(self._controller.state)

    def set_default_output_directory(self, value: str) -> None:
        """Use settings only as a default; it never mutates the global preference."""

        assert_ui_thread(self)
        self._default_directory = value
        if not self._location_was_edited:
            self.output_directory.setText(value)
        self._refresh_enqueue_enabled()

    def focus_url_input(self) -> None:
        self.url_input.setFocus()

    def render_state(self, state: HomeState) -> None:
        """Render controller state on the GUI thread without recreating the screen."""

        assert_ui_thread(self)
        busy = state.analysis.is_busy
        self.url_input.setEnabled(not busy)
        self.paste_button.setEnabled(not busy)
        self.clear_button.setEnabled(not busy and bool(self.url_input.text()))
        self.analyze_button.setEnabled(not busy and bool(self.url_input.text().strip()))
        self.cancel_button.setVisible(busy)
        self.analysis_progress.setVisible(busy)
        self.configuration_card.setVisible(self._configuration is not None and not busy)
        if busy:
            self.analysis_status.setText(self._text(StringKey.ANALYZING))
            self.analysis_status.setVisible(True)
            self._delayed_timer.start()
        else:
            self._delayed_timer.stop()

        if state.analysis.error is not None:
            self.error_label.setText(
                f"{self._text(StringKey.ERROR_GENERIC_TITLE)} — "
                f"{self._text(StringKey.ERROR_GENERIC_BODY)}"
            )
            self.error_label.setVisible(True)
        elif not busy:
            self.error_label.setVisible(False)

        if state.configuration is not None and state.configuration != self._configuration:
            self._apply_configuration(state.configuration)
        elif not busy and self._configuration is not None and not self._enqueue_was_busy:
            self.analysis_status.setText(self._text(StringKey.ANALYSIS_READY))
            self.analysis_status.setVisible(True)

        if self._enqueue_was_busy and not state.enqueue.is_busy:
            if state.enqueue.error is None:
                self.analysis_status.setText(self._text(StringKey.QUEUED))
                self.analysis_status.setVisible(True)
                self._is_dirty = False
                self.queued.emit()
            else:
                self.error_label.setText(
                    f"{self._text(StringKey.ERROR_GENERIC_TITLE)} — "
                    f"{self._text(StringKey.ERROR_GENERIC_BODY)}"
                )
                self.error_label.setVisible(True)
        self._enqueue_was_busy = state.enqueue.is_busy
        self.add_button.setText(
            self._text(StringKey.ADD_TO_DOWNLOADS) if not state.enqueue.is_busy else "…"
        )
        self._refresh_enqueue_enabled(state.enqueue.is_busy)

    def _build_url_card(self, parent: QWidget) -> QFrame:
        card = QFrame(parent)
        card.setObjectName("screenCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(
            TOKENS.spacing.standard,
            TOKENS.spacing.standard,
            TOKENS.spacing.standard,
            TOKENS.spacing.standard,
        )
        layout.setSpacing(TOKENS.spacing.small)
        label = QLabel(self._text(StringKey.HOME_URL_LABEL), card)
        layout.addWidget(label)
        row = QHBoxLayout()
        self.url_input = QLineEdit(card)
        self.url_input.setObjectName("homeUrlInput")
        self.url_input.setPlaceholderText(self._text(StringKey.HOME_URL_PLACEHOLDER))
        self.url_input.setClearButtonEnabled(False)
        self.url_input.textChanged.connect(self._url_changed)
        self.url_input.returnPressed.connect(self._request_analysis)
        row.addWidget(self.url_input, 1)
        self.paste_button = QPushButton(self._text(StringKey.PASTE), card)
        self.paste_button.clicked.connect(self._paste_explicitly)
        row.addWidget(self.paste_button)
        self.clear_button = QPushButton(self._text(StringKey.CLEAR), card)
        self.clear_button.clicked.connect(self.url_input.clear)
        row.addWidget(self.clear_button)
        self.analyze_button = QPushButton(self._text(StringKey.ANALYZE), card)
        self.analyze_button.setObjectName("primaryAction")
        self.analyze_button.clicked.connect(self._request_analysis)
        row.addWidget(self.analyze_button)
        layout.addLayout(row)
        self.analysis_status = QLabel(card)
        self.analysis_status.setObjectName("helperText")
        self.analysis_status.setVisible(False)
        layout.addWidget(self.analysis_status)
        self.analysis_progress = QProgressBar(card)
        self.analysis_progress.setRange(0, 0)
        self.analysis_progress.setTextVisible(False)
        self.analysis_progress.setVisible(False)
        layout.addWidget(self.analysis_progress)
        self.cancel_button = QPushButton(self._text(StringKey.CANCEL), card)
        self.cancel_button.clicked.connect(self._controller.cancel_analysis)
        self.cancel_button.setVisible(False)
        layout.addWidget(self.cancel_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.error_label = QLabel(card)
        self.error_label.setObjectName("errorText")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)
        return card

    def _build_configuration_card(self, parent: QWidget) -> QFrame:
        self.configuration_card = QFrame(parent)
        self.configuration_card.setObjectName("screenCard")
        layout = QVBoxLayout(self.configuration_card)
        layout.setContentsMargins(
            TOKENS.spacing.standard,
            TOKENS.spacing.standard,
            TOKENS.spacing.standard,
            TOKENS.spacing.standard,
        )
        layout.setSpacing(TOKENS.spacing.standard)
        self.media_title = QLabel(self.configuration_card)
        self.media_title.setWordWrap(True)
        self.media_title.setMaximumHeight(52)
        layout.addWidget(self.media_title)
        self.media_details = QLabel(self.configuration_card)
        self.media_details.setObjectName("secondaryText")
        self.media_details.setWordWrap(True)
        layout.addWidget(self.media_details)
        mode_row = QHBoxLayout()
        self.mode_group = QButtonGroup(self.configuration_card)
        self.video_button = QToolButton(self.configuration_card)
        self.video_button.setText(self._text(StringKey.VIDEO))
        self.video_button.setCheckable(True)
        self.audio_button = QToolButton(self.configuration_card)
        self.audio_button.setText(self._text(StringKey.AUDIO))
        self.audio_button.setCheckable(True)
        self.mode_group.addButton(self.video_button)
        self.mode_group.addButton(self.audio_button)
        self.video_button.clicked.connect(lambda: self._set_mode(MediaKind.VIDEO))
        self.audio_button.clicked.connect(lambda: self._set_mode(MediaKind.AUDIO))
        mode_row.addWidget(self.video_button)
        mode_row.addWidget(self.audio_button)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)
        preset_label = QLabel(self._text(StringKey.PRESET_LABEL), self.configuration_card)
        layout.addWidget(preset_label)
        self.preset_combo = QComboBox(self.configuration_card)
        self.preset_combo.currentIndexChanged.connect(self._preset_changed)
        layout.addWidget(self.preset_combo)
        self.conversion_notice = QLabel(
            self._text(StringKey.CONVERSION_REQUIRED), self.configuration_card
        )
        self.conversion_notice.setObjectName("helperText")
        self.conversion_notice.setWordWrap(True)
        layout.addWidget(self.conversion_notice)
        location_label = QLabel(self._text(StringKey.OUTPUT_LOCATION), self.configuration_card)
        layout.addWidget(location_label)
        location_row = QHBoxLayout()
        self.output_directory = QLineEdit(self.configuration_card)
        self.output_directory.textChanged.connect(self._location_changed)
        location_row.addWidget(self.output_directory, 1)
        choose = QPushButton(self._text(StringKey.CHOOSE_FOLDER), self.configuration_card)
        choose.clicked.connect(self._choose_directory)
        location_row.addWidget(choose)
        layout.addLayout(location_row)
        self.advanced_button = QToolButton(self.configuration_card)
        self.advanced_button.setText(self._text(StringKey.ADVANCED_OPTIONS))
        self.advanced_button.setCheckable(True)
        self.advanced_button.toggled.connect(self._advanced_changed)
        layout.addWidget(self.advanced_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.advanced_hint = QLabel(self.configuration_card)
        self.advanced_hint.setObjectName("helperText")
        self.advanced_hint.setWordWrap(True)
        self.advanced_hint.setVisible(False)
        layout.addWidget(self.advanced_hint)
        self.add_disabled_reason = QLabel(self.configuration_card)
        self.add_disabled_reason.setObjectName("helperText")
        self.add_disabled_reason.setVisible(False)
        layout.addWidget(self.add_disabled_reason)
        self.add_button = QPushButton(
            self._text(StringKey.ADD_TO_DOWNLOADS), self.configuration_card
        )
        self.add_button.setObjectName("primaryAction")
        self.add_button.clicked.connect(self._enqueue)
        layout.addWidget(self.add_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.configuration_card.setVisible(False)
        return self.configuration_card

    def _request_analysis(self) -> None:
        url = self.url_input.text().strip()
        if not url:
            self.error_label.setText(self._text(StringKey.URL_REQUIRED))
            self.error_label.setVisible(True)
            return
        if self._configuration is not None and self._is_dirty:
            dialog = QMessageBox(self)
            dialog.setWindowTitle(self._text(StringKey.NEW_URL_TITLE))
            dialog.setText(self._text(StringKey.NEW_URL_BODY))
            analyze_new = dialog.addButton(
                self._text(StringKey.ANALYZE_NEW), QMessageBox.ButtonRole.AcceptRole
            )
            dialog.addButton(self._text(StringKey.KEEP_CURRENT), QMessageBox.ButtonRole.RejectRole)
            dialog.exec()
            if dialog.clickedButton() is not analyze_new:
                return
        self._controller.analyze(url)

    def _paste_explicitly(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            self.url_input.setText(clipboard.text().strip())
        self.url_input.setFocus()

    def _apply_configuration(self, configuration: MediaConfigurationView) -> None:
        self._configuration = configuration
        self._is_dirty = False
        self.configuration_card.setVisible(True)
        self.media_title.setText(configuration.title)
        self.media_title.setToolTip(configuration.title)
        details = [configuration.source_name]
        if configuration.uploader:
            details.append(configuration.uploader)
        if configuration.duration_seconds is not None:
            details.append(_duration_text(configuration.duration_seconds))
        if configuration.playlist_item_count is not None:
            details.append(f"{configuration.playlist_item_count} items")
        self.media_details.setText(
            " · ".join(details) or self._text(StringKey.METADATA_UNAVAILABLE)
        )
        self._set_mode(
            MediaKind.VIDEO
            if any(preset.kind is MediaKind.VIDEO for preset in configuration.presets)
            else MediaKind.AUDIO,
            mark_dirty=False,
        )
        if not self._location_was_edited:
            self.output_directory.setText(self._default_directory)
        self.analysis_status.setText(self._text(StringKey.ANALYSIS_READY))
        self.analysis_status.setVisible(True)

    def _set_mode(self, mode: MediaKind, *, mark_dirty: bool = True) -> None:
        self._mode = mode
        self.video_button.setChecked(mode is MediaKind.VIDEO)
        self.audio_button.setChecked(mode is MediaKind.AUDIO)
        model = QStandardItemModel(self.preset_combo)
        for preset in self._configuration.presets if self._configuration else ():
            if preset.kind is not mode:
                continue
            item = QStandardItem(_preset_label(preset))
            item.setData(preset.preset_id, Qt.ItemDataRole.UserRole)
            item.setData(preset, Qt.ItemDataRole.UserRole + 1)
            if not preset.available:
                item.setEnabled(False)
                item.setToolTip(self._text(StringKey.PRESET_UNAVAILABLE))
            model.appendRow(item)
        self.preset_combo.setModel(model)
        self._preset_changed()
        if mark_dirty and self._configuration is not None:
            self._is_dirty = True

    def _preset_changed(self) -> None:
        preset = self.preset_combo.currentData(Qt.ItemDataRole.UserRole + 1)
        self.conversion_notice.setVisible(
            isinstance(preset, PresetOptionView) and preset.requires_processing
        )
        if self._configuration is not None:
            self._is_dirty = True
        self._refresh_enqueue_enabled()

    def _location_changed(self, _: str) -> None:
        if self._configuration is not None:
            self._location_was_edited = True
            self._is_dirty = True
        self._refresh_enqueue_enabled()

    def _advanced_changed(self, expanded: bool) -> None:
        self.advanced_hint.setText(self._text(StringKey.ADVANCED_UNAVAILABLE))
        self.advanced_hint.setVisible(expanded)
        if self._configuration is not None:
            self._is_dirty = True

    def _choose_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, self._text(StringKey.CHOOSE_FOLDER), self.output_directory.text()
        )
        if directory:
            self.output_directory.setText(directory)

    def _enqueue(self) -> None:
        preset_id = self.preset_combo.currentData(Qt.ItemDataRole.UserRole)
        output_directory = self.output_directory.text().strip()
        if not isinstance(preset_id, str) or not output_directory:
            self._refresh_enqueue_enabled()
            return
        self._controller.enqueue(preset_id=preset_id, output_directory=output_directory)

    def _url_changed(self, _: str) -> None:
        self.clear_button.setEnabled(bool(self.url_input.text()))
        self.analyze_button.setEnabled(
            bool(self.url_input.text().strip()) and not self._controller.state.analysis.is_busy
        )

    def _show_delayed_copy(self) -> None:
        if self._controller.state.analysis.is_busy:
            self.analysis_status.setText(self._text(StringKey.ANALYZING_DELAYED))

    def _refresh_enqueue_enabled(self, is_busy: bool | None = None) -> None:
        preset_id = self.preset_combo.currentData(Qt.ItemDataRole.UserRole)
        enabled = bool(self._configuration and preset_id and self.output_directory.text().strip())
        if is_busy is True:
            enabled = False
        self.add_button.setEnabled(enabled)
        if self._configuration is None:
            reason = ""
        elif not self.output_directory.text().strip():
            reason = self._text(StringKey.OUTPUT_REQUIRED)
        elif not preset_id:
            reason = self._text(StringKey.PRESET_UNAVAILABLE)
        else:
            reason = ""
        self.add_disabled_reason.setText(reason)
        self.add_disabled_reason.setVisible(bool(reason))

    def _text(self, key: StringKey) -> str:
        return self._localizer.text(key)


def _preset_label(preset: PresetOptionView) -> str:
    return " ".join(part for part in (preset.quality, preset.container) if part)


def _duration_text(seconds: float) -> str:
    total = max(0, round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"
