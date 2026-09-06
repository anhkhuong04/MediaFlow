from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Condition, Event, Lock, current_thread
from threading import enumerate as enumerate_threads

import pytest

from mediaflow.application import (
    CancellationToken,
    DownloadArtifact,
    DownloadJob,
    DownloadManager,
    DownloadOutcome,
    ProgressSink,
    QueueManager,
)
from mediaflow.domain import (
    AttemptId,
    DownloadRequest,
    DownloadTask,
    Failure,
    FailureCategory,
    OutputPath,
    SourceUrl,
    TaskId,
    TaskState,
    UtcTimestamp,
    VideoPreset,
)
from tests.unit.application.fakes import CollectingEventPublisher, InMemoryTaskRepository


class IncrementingClock:
    def __init__(self) -> None:
        self._lock = Lock()
        self._count = 0

    def now(self) -> UtcTimestamp:
        with self._lock:
            self._count += 1
            value = datetime(2026, 9, 7, tzinfo=UTC) + timedelta(seconds=self._count)
        return UtcTimestamp(value)


@dataclass(slots=True)
class GatedDownloader:
    output: OutputPath
    release: Event = field(default_factory=Event)
    started: list[str] = field(default_factory=list)
    worker_names: list[str] = field(default_factory=list)
    maximum_active: int = 0
    _active: int = 0
    _condition: Condition = field(default_factory=Condition)

    def download(
        self,
        job: DownloadJob,
        *,
        progress: ProgressSink,
        cancellation: CancellationToken,
    ) -> DownloadOutcome:
        del progress
        with self._condition:
            self._active += 1
            self.maximum_active = max(self.maximum_active, self._active)
            self.started.append(job.request.media_title)
            self.worker_names.append(current_thread().name)
            self._condition.notify_all()
        if not self.release.wait(timeout=5):
            raise TimeoutError("test gate was not released")
        with self._condition:
            self._active -= 1
        if cancellation.is_cancelled():
            return DownloadOutcome.failed(
                Failure(FailureCategory.CANCELLED, "download.cancelled", False)
            )
        return DownloadOutcome.succeeded(DownloadArtifact((self.output,), True))

    def wait_for_starts(self, count: int) -> None:
        with self._condition:
            assert self._condition.wait_for(lambda: len(self.started) >= count, timeout=5)


@dataclass(slots=True)
class IsolatedFailureDownloader:
    output: OutputPath
    started: list[str] = field(default_factory=list)

    def download(
        self,
        job: DownloadJob,
        *,
        progress: ProgressSink,
        cancellation: CancellationToken,
    ) -> DownloadOutcome:
        del progress, cancellation
        self.started.append(job.request.media_title)
        if job.request.media_title == "0":
            raise RuntimeError("one worker failed")
        return DownloadOutcome.succeeded(DownloadArtifact((self.output,), True))


def test_fifo_order_is_deterministic_with_one_slot(tmp_path: Path) -> None:
    repository, tasks = _tasks(tmp_path, count=4)
    downloader = GatedDownloader(OutputPath(tmp_path / "stream.webm"))
    queue = _queue(repository, downloader, concurrency=1)
    queue.enqueue_many(tuple(task.task_id for task in tasks))
    downloader.wait_for_starts(1)

    assert downloader.started == ["0"]
    downloader.release.set()
    assert queue.wait_for_idle(timeout_seconds=5)
    queue.shutdown()

    assert downloader.started == ["0", "1", "2", "3"]


def test_stress_never_exceeds_limit_and_runs_off_caller_thread(tmp_path: Path) -> None:
    repository, tasks = _tasks(tmp_path, count=12)
    downloader = GatedDownloader(OutputPath(tmp_path / "stream.webm"))
    queue = _queue(repository, downloader, concurrency=3)
    queue.enqueue_many(tuple(task.task_id for task in tasks))
    downloader.wait_for_starts(3)

    assert queue.active_count == 3
    assert downloader.maximum_active == 3
    assert all(name.startswith("mediaflow-download") for name in downloader.worker_names)
    assert current_thread().name not in downloader.worker_names

    downloader.release.set()
    assert queue.wait_for_idle(timeout_seconds=5)
    queue.shutdown()
    assert downloader.maximum_active <= 3
    assert len(downloader.started) == 12
    assert not any(
        thread.is_alive() and thread.name.startswith("mediaflow-download")
        for thread in enumerate_threads()
    )


def test_active_and_queued_cancel_release_slot_and_end_cancelled(tmp_path: Path) -> None:
    repository, tasks = _tasks(tmp_path, count=2)
    downloader = GatedDownloader(OutputPath(tmp_path / "stream.webm"))
    queue = _queue(repository, downloader, concurrency=1)
    queue.enqueue_many(tuple(task.task_id for task in tasks))
    downloader.wait_for_starts(1)

    assert queue.cancel(tasks[1].task_id)
    assert queue.cancel(tasks[0].task_id)
    downloader.release.set()
    assert queue.wait_for_idle(timeout_seconds=5)
    queue.shutdown()

    assert queue.active_count == 0
    assert queue.pending_count == 0
    assert downloader.started == ["0"]
    assert all(
        repository.get(task.task_id) is not None
        and repository.get(task.task_id).state is TaskState.CANCELLED  # type: ignore[union-attr]
        for task in tasks
    )


def test_one_worker_failure_does_not_stop_following_tasks_or_leak_slots(
    tmp_path: Path,
) -> None:
    repository, tasks = _tasks(tmp_path, count=3)
    downloader = IsolatedFailureDownloader(OutputPath(tmp_path / "stream.webm"))
    queue = _queue(repository, downloader, concurrency=1)
    queue.enqueue_many(tuple(task.task_id for task in tasks))

    assert queue.wait_for_idle(timeout_seconds=5)
    queue.shutdown()

    assert downloader.started == ["0", "1", "2"]
    assert repository.get(tasks[0].task_id).state is TaskState.FAILED  # type: ignore[union-attr]
    assert repository.get(tasks[1].task_id).state is TaskState.PROCESSING  # type: ignore[union-attr]
    assert repository.get(tasks[2].task_id).state is TaskState.PROCESSING  # type: ignore[union-attr]
    assert queue.active_count == queue.pending_count == 0
    with pytest.raises(RuntimeError, match="shutting down"):
        queue.enqueue(TaskId.new())


def _queue(
    repository: InMemoryTaskRepository,
    downloader: GatedDownloader | IsolatedFailureDownloader,
    *,
    concurrency: int,
) -> QueueManager:
    return QueueManager(
        DownloadManager(
            downloader=downloader,
            repository=repository,
            events=CollectingEventPublisher(),
            clock=IncrementingClock(),
        ),
        concurrency=concurrency,
    )


def _tasks(tmp_path: Path, *, count: int) -> tuple[InMemoryTaskRepository, list[DownloadTask]]:
    created_at = UtcTimestamp(datetime(2026, 9, 7, tzinfo=UTC))
    tasks = [
        DownloadTask.create(
            task_id=TaskId.new(),
            attempt_id=AttemptId.new(),
            request=DownloadRequest(
                SourceUrl(f"https://example.com/media/{index}"),
                str(index),
                VideoPreset(),
                OutputPath(tmp_path),
            ),
            created_at=created_at,
        )
        for index in range(count)
    ]
    return InMemoryTaskRepository({task.task_id: task for task in tasks}), tasks
