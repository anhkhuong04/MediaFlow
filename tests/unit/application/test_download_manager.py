from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mediaflow.application import (
    CancellationToken,
    DownloadArtifact,
    DownloadJob,
    DownloadManager,
    DownloadOutcome,
    ProgressPolicy,
    ProgressSink,
    TaskFailed,
    TaskProgressChanged,
    TaskStateChanged,
)
from mediaflow.domain import (
    AttemptId,
    DownloadRequest,
    DownloadTask,
    Failure,
    FailureCategory,
    OutputPath,
    ProgressSnapshot,
    SourceUrl,
    TaskId,
    TaskState,
    UtcTimestamp,
    VideoPreset,
)
from tests.unit.application.fakes import CollectingEventPublisher, InMemoryTaskRepository

BASE = datetime(2026, 9, 7, tzinfo=UTC)


@dataclass(slots=True)
class SequenceClock:
    values: list[UtcTimestamp]

    def now(self) -> UtcTimestamp:
        return self.values.pop(0)


@dataclass(slots=True)
class ScriptedDownloader:
    action: Callable[[DownloadJob, ProgressSink, CancellationToken], DownloadOutcome]
    jobs: list[DownloadJob] = field(default_factory=list)

    def download(
        self,
        job: DownloadJob,
        *,
        progress: ProgressSink,
        cancellation: CancellationToken,
    ) -> DownloadOutcome:
        self.jobs.append(job)
        return self.action(job, progress, cancellation)


def test_success_transitions_to_processing_and_returns_temporary_artifact(
    tmp_path: Path,
) -> None:
    repository, task = _repository_with_task(tmp_path)
    artifact = DownloadArtifact((OutputPath(tmp_path / "stream.webm"),), True)
    downloader = ScriptedDownloader(
        lambda job, progress, cancellation: DownloadOutcome.succeeded(artifact)
    )
    events = CollectingEventPublisher()
    manager = DownloadManager(
        downloader=downloader,
        repository=repository,
        events=events,
        clock=_clock(1, 2),
    )

    assert manager.execute(task.task_id) == artifact

    stored = repository.get(task.task_id)
    assert stored is not None and stored.state is TaskState.PROCESSING
    assert downloader.jobs[0].request == task.request
    assert [event.state for event in events.events if isinstance(event, TaskStateChanged)] == [
        TaskState.DOWNLOADING,
        TaskState.PROCESSING,
    ]


def test_failure_is_terminal_and_publishes_sanitized_failure(tmp_path: Path) -> None:
    repository, task = _repository_with_task(tmp_path)
    failure = Failure(FailureCategory.NETWORK, "download.network", retryable=True)
    manager = DownloadManager(
        downloader=ScriptedDownloader(
            lambda job, progress, cancellation: DownloadOutcome.failed(failure)
        ),
        repository=repository,
        events=(events := CollectingEventPublisher()),
        clock=_clock(1, 2),
    )

    assert manager.execute(task.task_id) is None

    stored = repository.get(task.task_id)
    assert stored is not None and stored.state is TaskState.FAILED
    assert stored.current_attempt.failure == failure
    assert any(isinstance(event, TaskFailed) for event in events.events)


def test_unexpected_worker_and_event_callback_failures_do_not_escape(tmp_path: Path) -> None:
    repository, task = _repository_with_task(tmp_path)

    def crash(
        job: DownloadJob, progress: ProgressSink, cancellation: CancellationToken
    ) -> DownloadOutcome:
        raise RuntimeError("engine callback leaked")

    manager = DownloadManager(
        downloader=ScriptedDownloader(crash),
        repository=repository,
        events=CollectingEventPublisher(fail=True),
        clock=_clock(1, 2),
    )

    assert manager.execute(task.task_id) is None
    stored = repository.get(task.task_id)
    assert stored is not None and stored.state is TaskState.FAILED
    assert stored.current_attempt.failure is not None
    assert stored.current_attempt.failure.code == "download.worker_unexpected"


def test_progress_is_coalesced_and_only_checkpointed_periodically(tmp_path: Path) -> None:
    operation_log: list[str] = []
    repository, task = _repository_with_task(tmp_path, operation_log=operation_log)
    artifact = DownloadArtifact((OutputPath(tmp_path / "stream.webm"),), True)

    def report_progress(
        job: DownloadJob, progress: ProgressSink, cancellation: CancellationToken
    ) -> DownloadOutcome:
        del job, cancellation
        for seconds, downloaded in ((2.0, 20), (2.1, 21), (8.0, 80), (8.1, 81)):
            progress.report(
                ProgressSnapshot.downloading(
                    captured_at=_timestamp(seconds),
                    downloaded_bytes=downloaded,
                    total_bytes=100,
                )
            )
        return DownloadOutcome.succeeded(artifact)

    events = CollectingEventPublisher()
    manager = DownloadManager(
        downloader=ScriptedDownloader(report_progress),
        repository=repository,
        events=events,
        clock=_clock(1, 20),
        progress_policy=ProgressPolicy(event_interval_seconds=0.25, checkpoint_interval_seconds=5),
    )

    manager.execute(task.task_id)

    progress_events = [event for event in events.events if isinstance(event, TaskProgressChanged)]
    assert [event.progress.downloaded_bytes for event in progress_events] == [20, 80, 81]
    assert operation_log.count("repository.replace") == 3


def test_cancel_queued_is_immediate(tmp_path: Path) -> None:
    repository, queued = _repository_with_task(tmp_path)
    manager = DownloadManager(
        downloader=ScriptedDownloader(
            lambda job, progress, cancellation: DownloadOutcome.failed(
                Failure(FailureCategory.CANCELLED, "download.cancelled", False)
            )
        ),
        repository=repository,
        events=CollectingEventPublisher(),
        clock=_clock(1),
    )

    assert manager.cancel(queued.task_id)
    stored = repository.get(queued.task_id)
    assert stored is not None and stored.state is TaskState.CANCELLED


def _repository_with_task(
    tmp_path: Path, *, operation_log: list[str] | None = None
) -> tuple[InMemoryTaskRepository, DownloadTask]:
    task = DownloadTask.create(
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
    return InMemoryTaskRepository({task.task_id: task}, operation_log), task


def _timestamp(seconds: float) -> UtcTimestamp:
    return UtcTimestamp(BASE + timedelta(seconds=seconds))


def _clock(*seconds: float) -> SequenceClock:
    return SequenceClock([_timestamp(value) for value in seconds])
