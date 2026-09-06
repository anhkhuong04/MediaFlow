import subprocess
import sys
from dataclasses import FrozenInstanceError, is_dataclass
from pathlib import Path
from typing import Any, TypeAliasType, get_args, get_origin, get_type_hints

import pytest

from mediaflow.application import (
    AnalysisFailed,
    AnalysisOutcome,
    AnalysisSucceeded,
    Analyzer,
    ApplicationEvent,
    ApplicationSettings,
    CancellationToken,
    Clock,
    DependencyComponent,
    DependencyInfo,
    DependencyProbe,
    DependencyReport,
    DependencyState,
    DiskSpaceEstimate,
    DownloadArtifact,
    Downloader,
    DownloadJob,
    DownloadOutcome,
    EventPublisher,
    MediaProcessor,
    OutputReady,
    ProcessingJob,
    ProcessingOutcome,
    ProgressSink,
    SettingsStore,
    TaskFailed,
    TaskProgressChanged,
    TaskQueued,
    TaskRepository,
    TaskStateChanged,
)
from mediaflow.domain import (
    AttemptId,
    DownloadRequest,
    Failure,
    FailureCategory,
    MediaInfo,
    MediaStream,
    OutputPath,
    SourceUrl,
    StreamKind,
    TaskId,
    UtcTimestamp,
    VideoPreset,
)
from tests.unit.application.fakes import (
    CollectingEventPublisher,
    FakeAnalyzer,
    FakeCancellationToken,
    FakeClock,
    FakeDependencyProbe,
    FakeDownloader,
    FakeMediaProcessor,
    FakeProgressSink,
    InMemorySettingsStore,
    InMemoryTaskRepository,
)

EVENT_TYPES = (
    AnalysisSucceeded,
    AnalysisFailed,
    TaskQueued,
    TaskStateChanged,
    TaskProgressChanged,
    OutputReady,
    TaskFailed,
)


def test_fake_adapters_satisfy_every_application_port(tmp_path: Path) -> None:
    output = OutputPath(tmp_path / "output.mp4")
    artifact = DownloadArtifact((output,), requires_processing=False)
    settings = ApplicationSettings(OutputPath(tmp_path), VideoPreset(), 2)

    analyzer: Analyzer = FakeAnalyzer(AnalysisOutcome.failed(_failure()))
    downloader: Downloader = FakeDownloader(artifact)
    processor: MediaProcessor = FakeMediaProcessor(output)
    repository: TaskRepository = InMemoryTaskRepository()
    settings_store: SettingsStore = InMemorySettingsStore(settings)
    publisher: EventPublisher = CollectingEventPublisher()
    clock: Clock = FakeClock([_timestamp()])
    cancellation: CancellationToken = FakeCancellationToken()
    progress: ProgressSink = FakeProgressSink()
    dependency_report = DependencyReport(
        tuple(
            DependencyInfo(component, DependencyState.NOT_FOUND)
            for component in DependencyComponent
        )
    )
    dependency_probe: DependencyProbe = FakeDependencyProbe(dependency_report)

    source = _source_url()
    request = DownloadRequest(source, "Media", VideoPreset(), OutputPath(tmp_path))
    assert analyzer.analyze(source, cancellation=cancellation).failure == _failure()
    job = DownloadJob(TaskId.new(), AttemptId.new(), request)
    assert downloader.download(job, progress=progress, cancellation=cancellation) == (
        DownloadOutcome.succeeded(artifact)
    )
    processing_job = ProcessingJob(job.task_id, job.attempt_id, request, artifact)
    assert processor.process(
        processing_job, progress=progress, cancellation=cancellation
    ) == ProcessingOutcome.succeeded(output)
    assert repository.list_downloads() == ()
    assert settings_store.load() == settings
    settings_store.save(settings)
    publisher.publish(AnalysisFailed(source, _failure(), _timestamp()))
    assert clock.now() == _timestamp()
    assert cancellation.is_cancelled() is False
    assert dependency_probe.probe() == dependency_report


def test_events_are_typed_immutable_and_contain_no_raw_contracts() -> None:
    assert isinstance(ApplicationEvent, TypeAliasType)
    assert set(get_args(ApplicationEvent.__value__)) == set(EVENT_TYPES)
    for event_type in EVENT_TYPES:
        assert is_dataclass(event_type)
        for annotation in get_type_hints(event_type).values():
            assert not _contains_raw_contract(annotation)

    event = AnalysisFailed(source_url=_source_url(), failure=_failure(), occurred_at=_timestamp())
    with pytest.raises(FrozenInstanceError):
        setattr(event, "occurred_at", _timestamp())  # noqa: B010


def test_application_imports_without_framework_or_infrastructure(tmp_path: Path) -> None:
    command = """
import sys
import mediaflow.application
forbidden = ("PySide6", "yt_dlp", "sqlite3")
assert not any(name == prefix or name.startswith(prefix + ".")
               for name in sys.modules for prefix in forbidden)
"""
    subprocess.run(
        [sys.executable, "-I", "-c", command],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_application_models_reject_ambiguous_or_empty_values(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        AnalysisOutcome()
    with pytest.raises(ValueError):
        AnalysisOutcome(media=_media(), failure=_failure())
    with pytest.raises(ValueError):
        DownloadArtifact((), requires_processing=False)
    path = OutputPath(tmp_path / "same.file")
    with pytest.raises(ValueError):
        DownloadArtifact((path, path), requires_processing=True)
    with pytest.raises(ValueError):
        DownloadOutcome()
    with pytest.raises(ValueError):
        DownloadOutcome(artifact=DownloadArtifact((path,), False), failure=_failure())
    with pytest.raises(ValueError):
        ProcessingOutcome()
    with pytest.raises(ValueError):
        DiskSpaceEstimate(-1, 1)
    with pytest.raises(ValueError):
        DependencyInfo(DependencyComponent.FFMPEG, DependencyState.READY)
    with pytest.raises(ValueError):
        DependencyReport((DependencyInfo(DependencyComponent.FFMPEG, DependencyState.NOT_FOUND),))
    with pytest.raises(ValueError):
        ApplicationSettings(OutputPath(tmp_path), concurrent_downloads=0)


def _contains_raw_contract(annotation: object) -> bool:
    if annotation in {Any, dict} or get_origin(annotation) is dict:
        return True
    return any(_contains_raw_contract(argument) for argument in get_args(annotation))


def _timestamp() -> UtcTimestamp:
    from datetime import UTC, datetime

    return UtcTimestamp(datetime(2026, 9, 6, tzinfo=UTC))


def _source_url() -> SourceUrl:
    return SourceUrl("https://example.com/media")


def _failure() -> Failure:
    return Failure(FailureCategory.NETWORK, "network.timeout", retryable=True)


def _media() -> MediaInfo:
    return MediaInfo(
        source_url=_source_url(),
        title="Media",
        source_name="Example",
        streams=(MediaStream(key="stream", kind=StreamKind.AUDIO_VIDEO),),
    )
