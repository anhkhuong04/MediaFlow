"""Deterministic FIFO scheduling for background download execution."""

import logging
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from threading import Condition, RLock
from time import monotonic

from mediaflow.application.download_manager import DownloadManager
from mediaflow.application.models import DownloadArtifact, ShutdownReport
from mediaflow.application.processing_manager import ProcessingManager
from mediaflow.domain import OutputPath, TaskId

_LOGGER = logging.getLogger("mediaflow.queue")
type _ExecutionResult = tuple[DownloadArtifact | None, OutputPath | None]


@dataclass(frozen=True, slots=True)
class _QueuedWork:
    task_id: TaskId
    artifact: DownloadArtifact | None = None


class QueueManager:
    """Dispatch FIFO work to a bounded pool; no download runs on the caller thread."""

    def __init__(
        self,
        download_manager: DownloadManager,
        *,
        concurrency: int,
        processing_manager: ProcessingManager | None = None,
    ) -> None:
        if concurrency < 1:
            raise ValueError("Queue concurrency must be positive")
        self._download_manager = download_manager
        self._processing_manager = processing_manager
        self._concurrency = concurrency
        self._executor = ThreadPoolExecutor(
            max_workers=concurrency, thread_name_prefix="mediaflow-download"
        )
        self._lock = RLock()
        self._idle = Condition(self._lock)
        self._pending: deque[_QueuedWork] = deque()
        self._active: dict[TaskId, Future[_ExecutionResult]] = {}
        self._artifacts: dict[TaskId, DownloadArtifact] = {}
        self._outputs: dict[TaskId, OutputPath] = {}
        self._accepting = True

    @property
    def concurrency(self) -> int:
        return self._concurrency

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active)

    def enqueue(self, task_id: TaskId) -> None:
        with self._lock:
            if not self._accepting:
                raise RuntimeError("Queue is shutting down")
            if any(work.task_id == task_id for work in self._pending) or task_id in self._active:
                raise ValueError("Task is already scheduled")
            self._pending.append(_QueuedWork(task_id))
            self._dispatch_locked()

    def enqueue_processing(self, task_id: TaskId, artifact: DownloadArtifact) -> None:
        if self._processing_manager is None:
            raise RuntimeError("Queue has no processing manager")
        with self._lock:
            if not self._accepting:
                raise RuntimeError("Queue is shutting down")
            if any(work.task_id == task_id for work in self._pending) or task_id in self._active:
                raise ValueError("Task is already scheduled")
            self._pending.append(_QueuedWork(task_id, artifact))
            self._dispatch_locked()

    def enqueue_many(self, task_ids: tuple[TaskId, ...]) -> None:
        for task_id in task_ids:
            self.enqueue(task_id)

    def cancel(self, task_id: TaskId) -> bool:
        with self._lock:
            pending = next((work for work in self._pending if work.task_id == task_id), None)
            if pending is not None:
                self._pending.remove(pending)
                was_scheduled = True
            else:
                was_scheduled = task_id in self._active
        cancelled = self._download_manager.cancel(task_id)
        processing_cancelled = (
            self._processing_manager.cancel(task_id)
            if self._processing_manager is not None
            else False
        )
        return was_scheduled or cancelled or processing_cancelled

    def take_artifact(self, task_id: TaskId) -> DownloadArtifact | None:
        with self._lock:
            return self._artifacts.pop(task_id, None)

    def take_output(self, task_id: TaskId) -> OutputPath | None:
        with self._lock:
            return self._outputs.pop(task_id, None)

    def wait_for_idle(self, *, timeout_seconds: float) -> bool:
        if timeout_seconds < 0:
            raise ValueError("Timeout cannot be negative")
        deadline = monotonic() + timeout_seconds
        with self._idle:
            while self._pending or self._active:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return False
                self._idle.wait(remaining)
            return True

    def shutdown(self, *, timeout_seconds: float = 30.0) -> ShutdownReport:
        """Stop admission, retain queued work, and interrupt active work truthfully."""

        with self._lock:
            self._accepting = False
            queued = tuple(work.task_id for work in self._pending)
            self._pending.clear()
            active = tuple(self._active)
            self._idle.notify_all()
        for task_id in active:
            self._download_manager.interrupt(task_id)
            if self._processing_manager is not None:
                self._processing_manager.interrupt(task_id)
        clean = self.wait_for_idle(timeout_seconds=timeout_seconds)
        self._executor.shutdown(wait=clean, cancel_futures=True)
        return ShutdownReport(clean, active, queued)

    def __enter__(self) -> "QueueManager":
        return self

    def __exit__(self, *exception: object) -> None:
        self.shutdown()

    def _dispatch_locked(self) -> None:
        while self._pending and len(self._active) < self._concurrency:
            work = self._pending.popleft()
            future = self._executor.submit(self._execute_task, work)
            self._active[work.task_id] = future
            future.add_done_callback(partial(self._completed, work.task_id))

    def _execute_task(self, work: _QueuedWork) -> _ExecutionResult:
        if work.artifact is not None:
            if self._processing_manager is None:
                return None, None
            return None, self._processing_manager.execute(work.task_id, work.artifact)
        artifact = self._download_manager.execute(work.task_id)
        if artifact is None or self._processing_manager is None:
            return artifact, None
        return None, self._processing_manager.execute(work.task_id, artifact)

    def _completed(self, task_id: TaskId, future: Future[_ExecutionResult]) -> None:
        artifact = None
        output = None
        try:
            artifact, output = future.result()
        except Exception:
            _LOGGER.warning("application.failed")
        finally:
            with self._idle:
                self._active.pop(task_id, None)
                if artifact is not None:
                    self._artifacts[task_id] = artifact
                if output is not None:
                    self._outputs[task_id] = output
                self._dispatch_locked()
                self._idle.notify_all()
