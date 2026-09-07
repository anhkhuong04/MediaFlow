from datetime import UTC, datetime

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox
from pytest import MonkeyPatch

from mediaflow.application import (
    ConflictPolicy,
    DiskSpaceEstimate,
    DownloadItemView,
    DownloadStatus,
    MediaKind,
    ShutdownReport,
    TaskActionsView,
    TaskDetailsView,
    UserMessage,
)
from mediaflow.presentation.coordinator import PresentationCoordinator
from mediaflow.presentation.diagnostics import ErrorDetailsDialog, details_for_task, redact_source
from mediaflow.presentation.dialogs import ConflictDialog, DiskSpaceWarningDialog
from mediaflow.presentation.lifecycle import DesktopLifecycle
from mediaflow.presentation.output_actions import QtOutputLauncher
from mediaflow.presentation.strings import Localizer
from mediaflow.presentation.window import MediaFlowWindow
from tests.presentation.test_bridge_and_controllers import FakePresentationFacade


def test_error_diagnostics_redact_authenticated_url_before_copying(qtbot: object) -> None:
    detail = _task_detail("https://example.com/watch/123?token=secret&cookie=also-secret#code=x")
    diagnostics = details_for_task(detail)
    dialog = ErrorDetailsDialog(diagnostics, Localizer(), None)
    _add_widget(qtbot, dialog)

    dialog.copy_diagnostics()
    clipboard = QApplication.clipboard()

    assert diagnostics.source == "https://example.com/watch/123"
    assert clipboard is not None
    assert "secret" not in clipboard.text()
    assert "cookie" not in clipboard.text()
    assert "authorization" not in clipboard.text().lower()


def test_diagnostics_rejects_malformed_or_credential_like_source() -> None:
    assert redact_source("not a URL?token=secret") == "[redacted source]"
    assert redact_source("https://user:password@example.com/video") == "https://example.com/video"


def test_conflict_default_and_disk_space_copy_are_safe(qtbot: object) -> None:
    conflict = ConflictDialog(Localizer(), None)
    warning = DiskSpaceWarningDialog(DiskSpaceEstimate(3 * 1024**3, 1024**3), Localizer(), None)
    _add_widget(qtbot, conflict)
    _add_widget(qtbot, warning)

    assert conflict.decision is ConflictPolicy.RENAME
    labels = warning.findChildren(QLabel)
    assert labels and "approximately" in labels[0].text()


def test_output_launcher_uses_local_file_url_without_shell(monkeypatch: MonkeyPatch) -> None:
    urls: list[QUrl] = []

    def capture(url: QUrl) -> bool:
        urls.append(url)
        return True

    monkeypatch.setattr("mediaflow.presentation.output_actions.QDesktopServices.openUrl", capture)
    launcher = QtOutputLauncher()

    assert launcher.open_file("C:\\Media Files\\clip.mp4", allowed=True)
    assert launcher.open_folder("C:\\Media Files\\clip.mp4", allowed=True)
    assert not launcher.open_file("C:\\ignored.mp4", allowed=False)
    assert all(url.isLocalFile() for url in urls)
    assert urls[0].toLocalFile().endswith("Media Files/clip.mp4")
    assert urls[1].toLocalFile().endswith("Media Files")


def test_shutdown_timeout_keeps_window_open_and_never_claims_clean_exit(
    qtbot: object, qapp: QApplication
) -> None:
    facade = FakePresentationFacade()
    coordinator = PresentationCoordinator(facade)
    window = MediaFlowWindow()
    _add_widget(qtbot, window)
    reports: list[object] = []
    lifecycle = DesktopLifecycle(
        qapp,
        window,
        coordinator,
        lambda: ShutdownReport(False, (), ()),
        lambda: True,
        Localizer(),
    )
    lifecycle.shutdown_completed.connect(reports.append)

    assert not lifecycle.request_exit()
    _wait_until(qtbot, lambda: reports == [ShutdownReport(False, (), ())])

    assert coordinator.is_closed
    assert window.isEnabled()
    assert window.isVisible()
    for dialog in qapp.topLevelWidgets():
        if isinstance(dialog, QMessageBox):
            dialog.reject()
    window.set_close_request_handler(None)
    window.close()


def _task_detail(source_url: str) -> TaskDetailsView:
    now = datetime(2026, 9, 7, tzinfo=UTC)
    item = DownloadItemView(
        task_id="a4b6d6ce-fcb9-4db9-a64e-5596b1c407d1",
        attempt_id="e727dd82-6c5b-4a5b-a0d7-641963de57f8",
        title="Example",
        preset_kind=MediaKind.VIDEO,
        quality="1080p",
        container="mp4",
        status=DownloadStatus.FAILED,
        created_at=now,
        updated_at=now,
        progress=None,
        failure=UserMessage("error.network.title", "error.network.body", "network.request-failed"),
        output_path=None,
        actions=TaskActionsView(False, True, False, True, False, False),
    )
    return TaskDetailsView(item, source_url, "C:\\Sensitive Path", ())


def _add_widget(qtbot: object, widget: object) -> None:
    add_widget = getattr(qtbot, "addWidget", None)
    if add_widget is None:
        raise AssertionError("pytest-qt did not provide qtbot.addWidget")
    add_widget(widget)


def _wait_until(qtbot: object, condition: object) -> None:
    wait_until = getattr(qtbot, "waitUntil", None)
    if wait_until is None:
        raise AssertionError("pytest-qt did not provide qtbot.waitUntil")
    wait_until(condition, timeout=2_000)
