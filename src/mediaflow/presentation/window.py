"""Minimal owned top-level window; navigation and screen content start in G1."""

from PySide6.QtCore import QObject, QThread
from PySide6.QtWidgets import QLabel, QMainWindow


class UiThreadViolation(RuntimeError):
    """A widget mutation was attempted outside its owning Qt thread."""


def assert_ui_thread(owner: QObject) -> None:
    """Fail fast in presentation code before a cross-thread widget mutation."""

    if owner.thread() != QThread.currentThread():
        raise UiThreadViolation("Qt widgets may only be updated from their owning thread")


class MediaFlowWindow(QMainWindow):
    """A deliberately small shell that gives G0 one owned, testable window."""

    def __init__(self) -> None:
        super().__init__()
        assert_ui_thread(self)
        self.setWindowTitle("MediaFlow")
        self.setMinimumSize(700, 500)
        self.resize(1000, 700)
        self.setCentralWidget(QLabel("MediaFlow", self))
