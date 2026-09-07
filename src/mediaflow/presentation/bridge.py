"""Qt-safe delivery of core events and presentation command completions."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import RLock
from typing import cast

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal

from mediaflow.application import (
    ApplicationEvent,
    CommandResult,
    OutputReady,
    TaskFailed,
    TaskProgressChanged,
    TaskQueued,
    TaskStateChanged,
    command_message,
)
from mediaflow.application.ports import EventSubscription
from mediaflow.presentation.contracts import PresentationFacade
from mediaflow.presentation.window import UiThreadViolation


@dataclass(frozen=True, slots=True)
class CommandKey:
    """Stable identity for one user intent, independent of widget instances."""

    screen: str
    action: str
    subject_id: str | None = None


@dataclass(frozen=True, slots=True)
class CommandCompletion:
    """A sanitized command result delivered only on the Qt UI thread."""

    key: CommandKey
    result: CommandResult[object]


class QtEventBridge(QObject):
    """Subscribe once to the core event source and marshal every update to Qt's thread."""

    application_event = Signal(object)
    command_completed = Signal(object)
    _incoming_event = Signal(object)
    _incoming_completion = Signal(object)

    def __init__(self, facade: PresentationFacade, *, progress_interval_ms: int = 40) -> None:
        super().__init__()
        if progress_interval_ms < 0:
            raise ValueError("Progress coalescing interval cannot be negative")
        self._facade = facade
        self._progress_interval_ms = progress_interval_ms
        self._subscription: EventSubscription | None = None
        self._closed = False
        self._lock = RLock()
        self._pending_progress: dict[str, TaskProgressChanged] = {}
        self._progress_timer = QTimer(self)
        self._progress_timer.setSingleShot(True)
        self._progress_timer.timeout.connect(self._flush_all_progress)
        self._incoming_event.connect(self._receive_event, Qt.ConnectionType.QueuedConnection)
        self._incoming_completion.connect(
            self._receive_completion, Qt.ConnectionType.QueuedConnection
        )

    @property
    def is_started(self) -> bool:
        return self._subscription is not None

    @property
    def is_closed(self) -> bool:
        return self._closed

    def start(self) -> None:
        """Own exactly one core subscription for this presentation session."""

        self._assert_ui_thread()
        if self._closed:
            raise RuntimeError("A closed Qt event bridge cannot be restarted")
        if self._subscription is None:
            self._subscription = self._facade.subscribe(self.post_application_event)

    def post_application_event(self, event: ApplicationEvent) -> None:
        """Accept a core event from any publishing thread without touching widgets."""

        with self._lock:
            if self._closed:
                return
        self._incoming_event.emit(event)

    def observe_future[T](self, key: CommandKey, future: Future[CommandResult[T]]) -> None:
        """Forward a facade future result through the same queued UI boundary."""

        future.add_done_callback(lambda completed: self._complete_future(key, completed))

    def post_command_completion(self, completion: CommandCompletion) -> None:
        """Accept a background command result; delivery occurs on the UI thread."""

        with self._lock:
            if self._closed:
                return
        self._incoming_completion.emit(completion)

    def close(self) -> None:
        """Release subscription, queued telemetry, and future delivery ownership once."""

        self._assert_ui_thread()
        with self._lock:
            if self._closed:
                return
            self._closed = True
        if self._subscription is not None:
            self._subscription.close()
            self._subscription = None
        self._progress_timer.stop()
        self._pending_progress.clear()

    def _complete_future[T](self, key: CommandKey, future: Future[CommandResult[T]]) -> None:
        try:
            result = cast(CommandResult[object], future.result())
        except Exception:
            # The boundary must never pass arbitrary executor errors into Qt/UI copy.
            result = CommandResult.failed(command_message("error.unexpected"))
        self.post_command_completion(CommandCompletion(key, result))

    def _receive_event(self, event: ApplicationEvent) -> None:
        self._assert_ui_thread()
        if self._closed:
            return
        if isinstance(event, TaskProgressChanged):
            self._pending_progress[str(event.task_id)] = event
            if not self._progress_timer.isActive():
                self._progress_timer.start(self._progress_interval_ms)
            return
        task_id = _event_task_id(event)
        if task_id is not None:
            self._flush_task_progress(task_id)
        self.application_event.emit(event)

    def _receive_completion(self, completion: CommandCompletion) -> None:
        self._assert_ui_thread()
        if not self._closed:
            self.command_completed.emit(completion)

    def _flush_all_progress(self) -> None:
        self._assert_ui_thread()
        if self._closed:
            return
        pending = tuple(self._pending_progress.values())
        self._pending_progress.clear()
        for event in pending:
            self.application_event.emit(event)

    def _flush_task_progress(self, task_id: str) -> None:
        event = self._pending_progress.pop(task_id, None)
        if event is not None:
            self.application_event.emit(event)

    def _assert_ui_thread(self) -> None:
        if self.thread() != QThread.currentThread():
            raise UiThreadViolation("Qt event bridge received work outside its owning UI thread")


class PresentationCommandRunner:
    """Run facade commands away from Qt while retaining per-intent busy ownership."""

    def __init__(self, bridge: QtEventBridge) -> None:
        self._bridge = bridge
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="mediaflow-presentation"
        )
        self._lock = RLock()
        self._busy: set[CommandKey] = set()
        self._closed = False

    def submit[T](self, key: CommandKey, operation: Callable[[], CommandResult[T]]) -> bool:
        """Schedule once; duplicate clicks remain rejected until UI consumes the result."""

        with self._lock:
            if self._closed or key in self._busy:
                return False
            self._busy.add(key)
        future = self._executor.submit(operation)
        future.add_done_callback(lambda completed: self._complete(key, completed))
        return True

    def release(self, key: CommandKey) -> None:
        """Mark a command available only after its queued UI completion was consumed."""

        with self._lock:
            self._busy.discard(key)

    def close(self) -> None:
        """Prevent new work and join presentation-owned command work before core shutdown."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=True)

    def _complete[T](self, key: CommandKey, future: Future[CommandResult[T]]) -> None:
        try:
            result = cast(CommandResult[object], future.result())
        except Exception:
            # Convert unexpected facade faults to the core's public safe message contract.
            result = CommandResult.failed(command_message("error.unexpected"))
        self._bridge.post_command_completion(CommandCompletion(key, result))


def _event_task_id(event: ApplicationEvent) -> str | None:
    if isinstance(event, (TaskQueued, TaskStateChanged, OutputReady, TaskFailed)):
        return str(event.task_id)
    return None
