"""Settings and first-run UI backed exclusively by the typed C8 facade."""

# ruff: noqa: E501

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from mediaflow.application import DependencyStatusView, SettingsView
from mediaflow.presentation.controllers import SettingsController, SettingsState
from mediaflow.presentation.design import TOKENS
from mediaflow.presentation.strings import Localizer, StringKey
from mediaflow.presentation.window import assert_ui_thread


class SettingsPage(QScrollArea):
    """A four-section preference screen with explicit save/reset semantics."""

    first_run_ready = Signal(object)

    def __init__(
        self,
        controller: SettingsController,
        *,
        logs_directory: Path | None = None,
        localizer: Localizer | None = None,
    ) -> None:
        super().__init__()
        self._controller = controller
        self._localizer = localizer or Localizer()
        self._logs_directory = logs_directory
        self._loaded: SettingsView | None = None
        self._dirty = False
        self._save_was_busy = False
        self._first_run_presented = False
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
        title = QLabel(self._text(StringKey.SETTINGS_TITLE), content)
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(self._general_section(content))
        layout.addWidget(self._downloads_section(content))
        layout.addWidget(self._media_section(content))
        layout.addWidget(self._advanced_section(content))
        self.error = QLabel(content)
        self.error.setObjectName("errorText")
        self.error.setVisible(False)
        layout.addWidget(self.error)
        self.saved = QLabel(content)
        self.saved.setObjectName("helperText")
        self.saved.setVisible(False)
        layout.addWidget(self.saved)
        actions = QHBoxLayout()
        self.reset_button = QPushButton(self._text(StringKey.RESET_CHANGES), content)
        self.reset_button.clicked.connect(self._reset)
        actions.addWidget(self.reset_button)
        self.save_button = QPushButton(self._text(StringKey.SAVE_CHANGES), content)
        self.save_button.setObjectName("primaryAction")
        self.save_button.clicked.connect(self._save)
        actions.addWidget(self.save_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addStretch(1)
        self._controller.state_changed.connect(self.render_state)
        self.render_state(self._controller.state)

    def render_state(self, state: SettingsState) -> None:
        assert_ui_thread(self)
        settings = state.settings
        save_completed = self._save_was_busy and not state.save.is_busy and state.save.error is None
        if settings is not None and (self._loaded is None or not self._dirty or save_completed):
            self._apply(settings)
        busy = state.save.is_busy
        self.save_button.setEnabled(self._dirty and not busy)
        self.reset_button.setEnabled(self._dirty and not busy)
        self.error.setVisible(state.save.error is not None)
        if state.save.error is not None:
            self.error.setText(self._text(StringKey.ERROR_GENERIC_BODY))
        if self._loaded is not None and not busy and state.save.error is None and not self._dirty:
            self.saved.setText(self._text(StringKey.SETTINGS_SAVED))
            self.saved.setVisible(True)
        self._render_dependencies(state.dependencies, state.dependencies_load.is_busy)
        if (
            settings is not None
            and state.dependencies
            and not settings.startup_check_seen
            and not self._first_run_presented
        ):
            self._first_run_presented = True
            self.first_run_ready.emit(state.dependencies)
        self._save_was_busy = state.save.is_busy

    def _general_section(self, parent: QWidget) -> QFrame:
        card, form = _section(self._text(StringKey.GENERAL), parent)
        self.theme = QComboBox(card)
        self._add_options(
            self.theme,
            (
                (self._text(StringKey.THEME_SYSTEM), "system"),
                (self._text(StringKey.THEME_LIGHT), "light"),
                (self._text(StringKey.THEME_DARK), "dark"),
            ),
        )
        self.language = QComboBox(card)
        self._add_options(
            self.language,
            (
                (self._text(StringKey.LANGUAGE_ENGLISH), "en"),
                (self._text(StringKey.LANGUAGE_VIETNAMESE), "vi"),
            ),
        )
        form.addRow(self._text(StringKey.THEME), self.theme)
        form.addRow(self._text(StringKey.LANGUAGE), self.language)
        hint = QLabel(self._text(StringKey.LANGUAGE_RESTART), card)
        hint.setObjectName("helperText")
        hint.setWordWrap(True)
        form.addRow("", hint)
        self.theme.currentIndexChanged.connect(self._changed)
        self.language.currentIndexChanged.connect(self._changed)
        return card

    def _downloads_section(self, parent: QWidget) -> QFrame:
        card, form = _section(self._text(StringKey.DOWNLOAD_SETTINGS), parent)
        folder_row = QHBoxLayout()
        self.folder = QLineEdit(card)
        self.folder.textChanged.connect(self._changed)
        folder_row.addWidget(self.folder, 1)
        choose = QPushButton(self._text(StringKey.CHOOSE_FOLDER), card)
        choose.clicked.connect(self._choose_folder)
        folder_row.addWidget(choose)
        folder_holder = QWidget(card)
        folder_holder.setLayout(folder_row)
        self.video_quality = QComboBox(card)
        self._add_options(
            self.video_quality,
            (
                ("Best", "best"),
                ("2160p", "2160p"),
                ("1440p", "1440p"),
                ("1080p", "1080p"),
                ("720p", "720p"),
            ),
        )
        self.video_container = QComboBox(card)
        self._add_options(self.video_container, (("MP4", "mp4"), ("MKV", "mkv")))
        self.concurrency = QSpinBox(card)
        self.concurrency.setRange(1, 8)
        form.addRow(self._text(StringKey.DEFAULT_FOLDER), folder_holder)
        form.addRow(self._text(StringKey.DEFAULT_QUALITY), self.video_quality)
        form.addRow(self._text(StringKey.DEFAULT_CONTAINER), self.video_container)
        form.addRow(self._text(StringKey.CONCURRENT_DOWNLOADS), self.concurrency)
        self.video_quality.currentIndexChanged.connect(self._changed)
        self.video_container.currentIndexChanged.connect(self._changed)
        self.concurrency.valueChanged.connect(self._changed)
        return card

    def _media_section(self, parent: QWidget) -> QFrame:
        card, form = _section(self._text(StringKey.MEDIA_SETTINGS), parent)
        self.audio_output = QComboBox(card)
        self._add_options(
            self.audio_output,
            (("Original", "original"), ("M4A", "m4a"), ("MP3", "mp3")),
        )
        form.addRow(self._text(StringKey.DEFAULT_AUDIO_OUTPUT), self.audio_output)
        self.audio_output.currentIndexChanged.connect(self._changed)
        return card

    def _advanced_section(self, parent: QWidget) -> QFrame:
        card, form = _section(self._text(StringKey.ADVANCED), parent)
        self.dependencies = QVBoxLayout()
        dependencies_holder = QWidget(card)
        dependencies_holder.setLayout(self.dependencies)
        form.addRow(self._text(StringKey.DEPENDENCIES), dependencies_holder)
        self.dependencies_progress = QProgressBar(card)
        self.dependencies_progress.setRange(0, 0)
        self.dependencies_progress.setVisible(False)
        form.addRow("", self.dependencies_progress)
        self.open_logs = QPushButton(self._text(StringKey.OPEN_LOGS), card)
        self.open_logs.setVisible(self._logs_directory is not None)
        self.open_logs.clicked.connect(self._open_logs)
        form.addRow("", self.open_logs)
        return card

    def _apply(self, settings: SettingsView) -> None:
        self._loaded = settings
        self._set_data(self.theme, settings.theme)
        self._set_data(self.language, settings.language)
        self.folder.setText(settings.default_output_directory)
        quality, container = _video_fields(settings.default_preset_id)
        self._set_data(self.video_quality, quality)
        self._set_data(self.video_container, container)
        self.concurrency.setValue(settings.concurrent_downloads)
        self._set_data(self.audio_output, _audio_container(settings.default_audio_preset_id))
        self._dirty = False
        self.saved.setVisible(False)

    def _save(self) -> None:
        folder = self.folder.text().strip()
        if not folder:
            self.error.setText(self._text(StringKey.OUTPUT_REQUIRED))
            self.error.setVisible(True)
            return
        self._controller.save(
            default_output_directory=folder,
            default_preset_id=(
                f"video.{self.video_quality.currentData()}.{self.video_container.currentData()}.auto"
            ),
            concurrent_downloads=self.concurrency.value(),
            default_audio_preset_id=f"audio.best.{self.audio_output.currentData()}.auto",
            theme=str(self.theme.currentData()),
            language=str(self.language.currentData()),
        )

    def _reset(self) -> None:
        if self._loaded is not None:
            self._apply(self._loaded)
        self.error.setVisible(False)

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, self._text(StringKey.CHOOSE_FOLDER), self.folder.text()
        )
        if folder:
            self.folder.setText(folder)

    def _open_logs(self) -> None:
        if self._logs_directory is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._logs_directory)))

    def _changed(self, *_: object) -> None:
        if self._loaded is not None:
            self._dirty = True
            self.saved.setVisible(False)
            self.save_button.setEnabled(True)
            self.reset_button.setEnabled(True)

    def _render_dependencies(
        self, dependencies: tuple[DependencyStatusView, ...], loading: bool
    ) -> None:
        self.dependencies_progress.setVisible(loading)
        while self.dependencies.count():
            item = self.dependencies.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for dependency in dependencies:
            label = QLabel(self._dependency_text(dependency), self.widget())
            label.setObjectName("secondaryText")
            label.setWordWrap(True)
            self.dependencies.addWidget(label)

    def _dependency_text(self, dependency: DependencyStatusView) -> str:
        if dependency.state == "ready" and dependency.version is not None:
            return f"{dependency.component}: {self._text(StringKey.DEPENDENCY_READY)} · {dependency.version}"
        return (
            f"{dependency.component}: {self._text(StringKey.DEPENDENCY_UNAVAILABLE)}\n"
            f"{self._text(StringKey.DEPENDENCY_EFFECT)}"
        )

    def _add_options(self, combo: QComboBox, options: tuple[tuple[str, str], ...]) -> None:
        for label, value in options:
            combo.addItem(label, value)

    @staticmethod
    def _set_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _text(self, key: StringKey) -> str:
        return self._localizer.text(key)


class FirstRunDialog(QDialog):
    """Small non-blocking dependency acknowledgement; it never prevents app use."""

    continued = Signal()
    configure_requested = Signal()

    def __init__(
        self,
        dependencies: tuple[DependencyStatusView, ...],
        localizer: Localizer,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.setModal(False)
        missing_ffmpeg = any(
            item.component == "ffmpeg" and item.state != "ready" for item in dependencies
        )
        self.setWindowTitle(
            localizer.text(
                StringKey.FIRST_RUN_ATTENTION_TITLE
                if missing_ffmpeg
                else StringKey.FIRST_RUN_READY_TITLE
            )
        )
        layout = QVBoxLayout(self)
        body = QLabel(
            localizer.text(
                StringKey.FIRST_RUN_ATTENTION_BODY
                if missing_ffmpeg
                else StringKey.FIRST_RUN_READY_BODY
            ),
            self,
        )
        body.setWordWrap(True)
        layout.addWidget(body)
        buttons = QDialogButtonBox(self)
        continue_button = buttons.addButton(
            localizer.text(StringKey.CONTINUE), QDialogButtonBox.ButtonRole.AcceptRole
        )
        continue_button.clicked.connect(self._continue)
        if missing_ffmpeg:
            configure = buttons.addButton(
                localizer.text(StringKey.CONFIGURE), QDialogButtonBox.ButtonRole.ActionRole
            )
            configure.clicked.connect(self._configure)
        layout.addWidget(buttons)

    def _continue(self) -> None:
        self.continued.emit()
        self.accept()

    def _configure(self) -> None:
        self.configure_requested.emit()
        self.accept()


def _section(title: str, parent: QWidget) -> tuple[QFrame, QFormLayout]:
    card = QFrame(parent)
    card.setObjectName("screenCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(
        TOKENS.spacing.standard,
        TOKENS.spacing.standard,
        TOKENS.spacing.standard,
        TOKENS.spacing.standard,
    )
    heading = QLabel(title, card)
    heading.setObjectName("sectionTitle")
    layout.addWidget(heading)
    form = QFormLayout()
    form.setSpacing(TOKENS.spacing.small)
    layout.addLayout(form)
    return card, form


def _video_fields(preset_id: str) -> tuple[str, str]:
    parts = preset_id.split(".")
    return (parts[1], parts[2]) if len(parts) == 4 and parts[0] == "video" else ("best", "mp4")


def _audio_container(preset_id: str) -> str:
    parts = preset_id.split(".")
    return parts[2] if len(parts) == 4 and parts[0] == "audio" else "original"
