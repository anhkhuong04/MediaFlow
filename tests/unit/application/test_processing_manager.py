from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, current_thread

from mediaflow.application import (
    CancellationToken,
    DownloadArtifact,
    DownloadManager,
    DownloadOutcome,
    OutputReady,
    ProcessingJob,
    ProcessingManager,
    ProcessingOutcome,
    ProgressSink,
    QueueManager,
    TaskFailed,
)
from mediaflow.domain import (
    AttemptId,
    DownloadRequest,
    DownloadTask,
    Failure,
    FailureCategory,
    OutputPath,
    SourceUrl,
    StreamKind,
    TaskId,
    TaskState,
    UtcTimestamp,
    VideoPreset,
)
from tests.unit.application.fakes import CollectingEventPublisher, InMemoryTaskRepository

BASE = datetime(2026, 9, 7, tzinfo=UTC)


@dataclass(slots=True)
class SequenceClock:
    seconds: list[int]

    def now(self) -> UtcTimestamp:
        return UtcTimestamp(BASE + timedelta(seconds=self.seconds.pop(0)))


@dataclass(slots=True)
class FakeProcessor:
    action: Callable[[ProcessingJob, CancellationToken], ProcessingOutcome]
    jobs: list[ProcessingJob] = field(default_factory=list)
    thread_names: list[str] = field(default_factory=list)

    def process(
        self,
        job: ProcessingJob,
        *,
        progress: ProgressSink,
        cancellation: CancellationToken,
    ) -> ProcessingOutcome:
        del progress
        self.jobs.append(job)
        self.thread_names.append(current_thread().name)
        return self.action(job, cancellation)


@dataclass(slots=True)
class FakeDownloader:
    artifact: DownloadArtifact

    def download(
        self,
        job: object,
        *,
        progress: ProgressSink,
        cancellation: CancellationToken,
    ) -> DownloadOutcome:
        del job, progress, cancellation
        return DownloadOutcome.succeeded(self.artifact)


@dataclass(slots=True)
class GatedProcessor:
    started: Event = field(default_factory=Event)
    release: Event = field(default_factory=Event)

    def process(
        self,
        job: ProcessingJob,
        *,
        progress: ProgressSink,
        cancellation: CancellationToken,
    ) -> ProcessingOutcome:
        del job, progress
        self.started.set()
        assert self.release.wait(timeout=5)
        if cancellation.is_cancelled():
            return ProcessingOutcome.failed(
                Failure(FailureCategory.CANCELLED, "processing.cancelled", False)
            )
        raise AssertionError("test expected cancellation")


def test_only_verified_processor_success_can_complete_and_emit_output(tmp_path: Path) -> None:
    repository, task = _processing_task(tmp_path)
    output = OutputPath(tmp_path / "final.mp4")
    output.value.write_bytes(b"verified")
    processor = FakeProcessor(lambda job, cancellation: ProcessingOutcome.succeeded(output))
    events = CollectingEventPublisher()
    manager = ProcessingManager(
        processor=processor,
        repository=repository,
        events=events,
        clock=SequenceClock([3]),
    )

    assert manager.execute(task.task_id, _artifact(tmp_path, task)) == output

    stored = repository.get(task.task_id)
    assert stored is not None and stored.state is TaskState.COMPLETED
    assert stored.current_attempt.output_path == output
    assert any(isinstance(event, OutputReady) for event in events.events)


def test_processing_failure_never_sets_completed_and_keeps_retryable_error(
    tmp_path: Path,
) -> None:
    repository, task = _processing_task(tmp_path)
    failure = Failure(FailureCategory.PROCESSING, "processing.ffmpeg_failed", retryable=True)
    events = CollectingEventPublisher()
    manager = ProcessingManager(
        processor=FakeProcessor(lambda job, cancellation: ProcessingOutcome.failed(failure)),
        repository=repository,
        events=events,
        clock=SequenceClock([3]),
    )

    assert manager.execute(task.task_id, _artifact(tmp_path, task)) is None
    stored = repository.get(task.task_id)
    assert stored is not None and stored.state is TaskState.FAILED
    assert stored.current_attempt.output_path is None
    assert any(isinstance(event, TaskFailed) for event in events.events)


def test_cancel_in_download_to_processing_handoff_window_is_not_lost(
    tmp_path: Path,
) -> None:
    repository, task = _processing_task(tmp_path)
    manager = ProcessingManager(
        processor=FakeProcessor(
            lambda job, cancellation: ProcessingOutcome.failed(
                Failure(FailureCategory.CANCELLED, "processing.cancelled", False)
            )
        ),
        repository=repository,
        events=CollectingEventPublisher(),
        clock=SequenceClock([3]),
    )

    assert manager.cancel(task.task_id)
    stored = repository.get(task.task_id)
    assert stored is not None and stored.state is TaskState.CANCELLED
    assert manager.execute(task.task_id, _artifact(tmp_path, task)) is None


def test_processing_only_retry_starts_processing_attempt_without_downloader(
    tmp_path: Path,
) -> None:
    repository, processing = _processing_task(tmp_path)
    failed = processing.transition(
        TaskState.FAILED,
        at=_timestamp(3),
        failure=Failure(
            FailureCategory.PROCESSING,
            "processing.ffmpeg_failed",
            retryable=True,
        ),
    )
    repository.tasks[processing.task_id] = failed
    output = OutputPath(tmp_path / "retry.mp4")
    output.value.write_bytes(b"verified")
    processor = FakeProcessor(lambda job, cancellation: ProcessingOutcome.succeeded(output))
    manager = ProcessingManager(
        processor=processor,
        repository=repository,
        events=CollectingEventPublisher(),
        clock=SequenceClock([4, 5]),
    )
    artifact = _artifact(tmp_path, processing)

    assert manager.retry(processing.task_id, artifact) == output

    stored = repository.get(processing.task_id)
    assert stored is not None and stored.state is TaskState.COMPLETED
    assert len(stored.attempts) == 2
    assert stored.attempts[0].state is TaskState.FAILED
    assert stored.attempts[1].state is TaskState.COMPLETED
    assert processor.jobs[0].artifact == artifact


def test_queue_keeps_slot_through_processing_and_runs_it_off_caller_thread(
    tmp_path: Path,
) -> None:
    queued = _queued_task(tmp_path)
    repository = InMemoryTaskRepository({queued.task_id: queued})
    artifact = _artifact(tmp_path, queued)
    output = OutputPath(tmp_path / "final.mp4")
    output.value.write_bytes(b"verified")
    clock = SequenceClock([1, 2, 3])
    events = CollectingEventPublisher()
    processor = FakeProcessor(lambda job, cancellation: ProcessingOutcome.succeeded(output))
    processing_manager = ProcessingManager(
        processor=processor, repository=repository, events=events, clock=clock
    )
    queue = QueueManager(
        DownloadManager(
            downloader=FakeDownloader(artifact),
            repository=repository,
            events=events,
            clock=clock,
        ),
        concurrency=1,
        processing_manager=processing_manager,
    )

    queue.enqueue(queued.task_id)
    assert queue.wait_for_idle(timeout_seconds=5)
    queue.shutdown()

    stored = repository.get(queued.task_id)
    assert stored is not None and stored.state is TaskState.COMPLETED
    assert queue.take_output(queued.task_id) == output
    assert processor.thread_names[0].startswith("mediaflow-download")
    assert processor.thread_names[0] != current_thread().name


def test_queue_cooperatively_cancels_active_processing_and_releases_slot(
    tmp_path: Path,
) -> None:
    queued = _queued_task(tmp_path)
    repository = InMemoryTaskRepository({queued.task_id: queued})
    artifact = _artifact(tmp_path, queued)
    clock = SequenceClock([1, 2, 3])
    processor = GatedProcessor()
    processing_manager = ProcessingManager(
        processor=processor,
        repository=repository,
        events=CollectingEventPublisher(),
        clock=clock,
    )
    queue = QueueManager(
        DownloadManager(
            downloader=FakeDownloader(artifact),
            repository=repository,
            events=CollectingEventPublisher(),
            clock=clock,
        ),
        concurrency=1,
        processing_manager=processing_manager,
    )
    queue.enqueue(queued.task_id)
    assert processor.started.wait(timeout=5)

    assert queue.cancel(queued.task_id)
    processor.release.set()
    assert queue.wait_for_idle(timeout_seconds=5)
    queue.shutdown()

    stored = repository.get(queued.task_id)
    assert stored is not None and stored.state is TaskState.CANCELLED
    assert queue.active_count == queue.pending_count == 0


def _queued_task(tmp_path: Path) -> DownloadTask:
    return DownloadTask.create(
        task_id=TaskId.new(),
        attempt_id=AttemptId.new(),
        request=DownloadRequest(
            SourceUrl("https://example.com/media"),
            "Media",
            VideoPreset(),
            OutputPath(tmp_path),
        ),
        created_at=_timestamp(0),
    )


def _processing_task(tmp_path: Path) -> tuple[InMemoryTaskRepository, DownloadTask]:
    queued = _queued_task(tmp_path)
    processing = queued.transition(TaskState.DOWNLOADING, at=_timestamp(1)).transition(
        TaskState.PROCESSING, at=_timestamp(2)
    )
    return InMemoryTaskRepository({processing.task_id: processing}), processing


def _artifact(tmp_path: Path, task: DownloadTask) -> DownloadArtifact:
    staging = (
        tmp_path / ".mediaflow-staging" / str(task.task_id) / str(task.current_attempt.attempt_id)
    )
    staging.mkdir(parents=True, exist_ok=True)
    media = staging / "media.mp4"
    media.write_bytes(b"temporary")
    return DownloadArtifact((OutputPath(media),), True, (StreamKind.AUDIO_VIDEO,))


def _timestamp(seconds: int) -> UtcTimestamp:
    return UtcTimestamp(BASE + timedelta(seconds=seconds))
