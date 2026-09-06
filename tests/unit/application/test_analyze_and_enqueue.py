from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mediaflow.application import (
    AnalysisFailed,
    AnalysisOutcome,
    AnalysisSucceeded,
    AnalyzeUrl,
    EnqueueDownload,
    TaskQueued,
)
from mediaflow.domain import (
    AnalysisState,
    Failure,
    FailureCategory,
    MediaInfo,
    MediaStream,
    OutputPath,
    SourceUrl,
    StreamKind,
    TaskState,
    UtcTimestamp,
    VideoPreset,
)
from tests.unit.application.fakes import (
    CollectingEventPublisher,
    FakeAnalyzer,
    FakeCancellationToken,
    FakeClock,
    InMemoryTaskRepository,
)


def at(seconds: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 9, 6, tzinfo=UTC) + timedelta(seconds=seconds))


def media(source: SourceUrl) -> MediaInfo:
    return MediaInfo(
        source_url=source,
        title="Normalized title",
        source_name="Example",
        streams=(MediaStream(key="normalized", kind=StreamKind.AUDIO_VIDEO),),
    )


def test_fake_analyzer_to_queued_task_without_raw_metadata(tmp_path: Path) -> None:
    source = SourceUrl("https://example.com/watch/1")
    normalized = media(SourceUrl("https://cdn.example.com/canonical/1"))
    analyzer = FakeAnalyzer(AnalysisOutcome.succeeded(normalized))
    events = CollectingEventPublisher()

    analysis = AnalyzeUrl(analyzer, events, FakeClock([at(0), at(1)])).execute(
        source, cancellation=FakeCancellationToken()
    )
    assert analysis.state is AnalysisState.SUCCEEDED
    assert analysis.result is normalized
    assert isinstance(events.events[0], AnalysisSucceeded)

    repository = InMemoryTaskRepository()
    task = EnqueueDownload(repository, events, FakeClock([at(2)])).execute(
        media=normalized, preset=VideoPreset(), output_directory=tmp_path_value(tmp_path)
    )
    assert task.state is TaskState.QUEUED
    assert task.request.source_url == normalized.source_url
    assert repository.get(task.task_id) == task
    assert isinstance(events.events[-1], TaskQueued)


def test_analysis_failure_is_sanitized_and_not_persisted() -> None:
    source = SourceUrl("https://example.com/missing")
    failure = Failure(FailureCategory.MEDIA_UNAVAILABLE, "media.unavailable", retryable=False)
    analyzer = FakeAnalyzer(AnalysisOutcome.failed(failure))
    events = CollectingEventPublisher()

    operation = AnalyzeUrl(analyzer, events, FakeClock([at(0), at(1)])).execute(
        source, cancellation=FakeCancellationToken()
    )
    assert operation.state is AnalysisState.FAILED
    assert operation.failure == failure
    assert events.events == [AnalysisFailed(source, failure, at(1))]


@pytest.mark.parametrize("token_values", [[True], [False, True]])
def test_analysis_cancellation_before_or_after_adapter(token_values: list[bool]) -> None:
    source = SourceUrl("https://example.com/media")
    analyzer = FakeAnalyzer(AnalysisOutcome.succeeded(media(source)))
    events = CollectingEventPublisher()
    operation = AnalyzeUrl(analyzer, events, FakeClock([at(0), at(1)])).execute(
        source, cancellation=FakeCancellationToken(token_values)
    )
    assert operation.state is AnalysisState.CANCELLED
    event = events.events[0]
    assert isinstance(event, AnalysisFailed)
    assert event.failure.category is FailureCategory.CANCELLED
    assert len(analyzer.calls) == (0 if token_values == [True] else 1)


def test_repository_commit_precedes_event_and_survives_delivery_failure(tmp_path: Path) -> None:
    operation_log: list[str] = []
    repository = InMemoryTaskRepository(operation_log=operation_log)
    events = CollectingEventPublisher(operation_log=operation_log, fail=True)
    normalized = media(SourceUrl("https://example.com/media"))
    use_case = EnqueueDownload(repository, events, FakeClock([at(0)]))

    with pytest.raises(RuntimeError, match="event delivery"):
        use_case.execute(
            media=normalized,
            preset=VideoPreset(),
            output_directory=tmp_path_value(tmp_path),
        )

    assert operation_log == ["repository.add", "event.publish"]
    assert len(repository.tasks) == 1


def tmp_path_value(path: Path) -> OutputPath:
    return OutputPath(path)
