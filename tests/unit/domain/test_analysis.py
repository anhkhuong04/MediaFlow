from datetime import UTC, datetime, timedelta

import pytest

from mediaflow.domain import (
    AnalysisOperation,
    AnalysisState,
    Failure,
    FailureCategory,
    InvalidAnalysisTransition,
    MediaInfo,
    MediaStream,
    SourceUrl,
    StreamKind,
    UtcTimestamp,
)


def at(seconds: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 9, 6, tzinfo=UTC) + timedelta(seconds=seconds))


def media(source: SourceUrl) -> MediaInfo:
    return MediaInfo(
        source_url=source,
        title="Example",
        source_name="Example",
        streams=(MediaStream(key="stream", kind=StreamKind.AUDIO_VIDEO),),
    )


def test_analysis_success_is_separate_from_download_task() -> None:
    source = SourceUrl("https://example.com/media")
    operation = AnalysisOperation.start(source_url=source, at=at(0))
    completed = operation.succeed(media=media(source), at=at(1))
    assert completed.state is AnalysisState.SUCCEEDED
    assert completed.result == media(source)
    assert completed.finished_at == at(1)


def test_analysis_failure_and_cancel_have_distinct_terminal_states() -> None:
    source = SourceUrl("https://example.com/media")
    operation = AnalysisOperation.start(source_url=source, at=at(0))
    failure = Failure(FailureCategory.NETWORK, "network.timeout", retryable=True)
    assert operation.fail(failure=failure, at=at(1)).state is AnalysisState.FAILED
    cancelled = operation.cancel(at=at(1))
    assert cancelled.state is AnalysisState.CANCELLED
    assert cancelled.failure is None


def test_analysis_terminal_state_cannot_transition_again() -> None:
    source = SourceUrl("https://example.com/media")
    completed = AnalysisOperation.start(source_url=source, at=at(0)).succeed(
        media=media(source), at=at(1)
    )
    with pytest.raises(InvalidAnalysisTransition):
        completed.cancel(at=at(2))


def test_analysis_accepts_canonical_source_and_rejects_backwards_time() -> None:
    source = SourceUrl("https://example.com/media")
    operation = AnalysisOperation.start(source_url=source, at=at(1))
    other_media = media(SourceUrl("https://example.com/other"))
    succeeded = operation.succeed(media=other_media, at=at(2))
    assert succeeded.result == other_media
    with pytest.raises(ValueError):
        operation.cancel(at=at(0))


def test_cancelled_failure_category_uses_cancel_operation() -> None:
    source = SourceUrl("https://example.com/media")
    operation = AnalysisOperation.start(source_url=source, at=at(0))
    failure = Failure(FailureCategory.CANCELLED, "analysis.cancelled", retryable=False)
    with pytest.raises(ValueError):
        operation.fail(failure=failure, at=at(1))
