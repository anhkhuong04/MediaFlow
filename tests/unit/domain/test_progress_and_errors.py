from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from mediaflow.domain import Failure, FailureCategory, ProgressSnapshot, ProgressStage, UtcTimestamp

NOW = UtcTimestamp(datetime(2026, 9, 6, tzinfo=UTC))


def test_unknown_progress_values_remain_none() -> None:
    progress = ProgressSnapshot.downloading(captured_at=NOW, downloaded_bytes=128)
    assert progress.fraction is None
    assert progress.total_bytes is None
    assert progress.speed_bytes_per_second is None
    assert progress.eta_seconds is None


def test_download_progress_computes_and_caps_fraction() -> None:
    complete = ProgressSnapshot.downloading(
        captured_at=NOW,
        downloaded_bytes=120,
        total_bytes=100,
        speed_bytes_per_second=0,
        eta_seconds=0,
    )
    assert complete.fraction == 1.0
    assert complete.speed_bytes_per_second == 0


def test_processing_progress_can_be_indeterminate() -> None:
    progress = ProgressSnapshot.processing(captured_at=NOW)
    assert progress.stage is ProgressStage.PROCESSING
    assert progress.fraction is None


@pytest.mark.parametrize(
    "progress",
    [
        lambda: ProgressSnapshot.processing(captured_at=NOW, fraction=-0.1),
        lambda: ProgressSnapshot.processing(captured_at=NOW, fraction=1.1),
        lambda: ProgressSnapshot.downloading(captured_at=NOW, downloaded_bytes=-1),
        lambda: ProgressSnapshot.downloading(captured_at=NOW, downloaded_bytes=1, total_bytes=0),
        lambda: ProgressSnapshot(stage=ProgressStage.DOWNLOADING, captured_at=NOW, total_bytes=10),
        lambda: ProgressSnapshot(
            stage=ProgressStage.DOWNLOADING,
            captured_at=NOW,
            downloaded_bytes=1,
            total_bytes=2,
            fraction=0.75,
        ),
    ],
)
def test_progress_rejects_invalid_values(progress: Callable[[], object]) -> None:
    with pytest.raises(ValueError):
        progress()


def test_failure_is_sanitized_and_machine_readable() -> None:
    failure = Failure(FailureCategory.NETWORK, "network.connection_lost", retryable=True)
    assert failure.category is FailureCategory.NETWORK
    assert failure.retryable is True
    with pytest.raises(ValueError):
        Failure(FailureCategory.UNEXPECTED, "Raw error: token=secret", retryable=False)


def test_failure_taxonomy_is_complete() -> None:
    assert {category.value for category in FailureCategory} == {
        "invalid_input",
        "unsupported_source",
        "media_unavailable",
        "auth_required",
        "access_denied",
        "network",
        "disk_space",
        "dependency",
        "output_conflict",
        "download",
        "processing",
        "cancelled",
        "unexpected",
    }
