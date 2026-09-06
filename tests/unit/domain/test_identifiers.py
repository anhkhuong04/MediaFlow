from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from mediaflow.domain import AttemptId, OutputPath, SourceUrl, TaskId, UtcTimestamp


def test_identifiers_reject_nil_uuid() -> None:
    with pytest.raises(ValueError, match="nil UUID"):
        TaskId(UUID(int=0))
    with pytest.raises(ValueError, match="nil UUID"):
        AttemptId(UUID(int=0))


def test_identifiers_round_trip_and_remain_distinct_types() -> None:
    task_id = TaskId.new()
    attempt_id = AttemptId.new()
    assert TaskId.parse(str(task_id)) == task_id
    assert AttemptId.parse(str(attempt_id)) == attempt_id
    assert task_id.value != attempt_id.value


@pytest.mark.parametrize(
    "value",
    [
        "",
        " https://example.com/media",
        "ftp://example.com/media",
        "https:///missing-host",
        "https://user:secret@example.com/media",
        "https://example.com:99999/media",
        "https://example.com/media\n",
    ],
)
def test_source_url_rejects_unsafe_or_malformed_values(value: str) -> None:
    with pytest.raises(ValueError):
        SourceUrl(value)


def test_source_url_accepts_http_url_with_query_and_fragment() -> None:
    value = "https://example.com/watch?v=abc#chapter"
    assert str(SourceUrl(value)) == value


def test_output_path_requires_an_absolute_path(tmp_path: Path) -> None:
    assert str(OutputPath(tmp_path)) == str(tmp_path)
    with pytest.raises(ValueError):
        OutputPath(Path("relative/downloads"))


def test_timestamp_requires_utc_and_orders_values() -> None:
    first = UtcTimestamp(datetime(2026, 9, 6, tzinfo=UTC))
    second = UtcTimestamp(datetime(2026, 9, 6, 0, 0, 1, tzinfo=UTC))
    assert first < second
    assert UtcTimestamp.now().value.utcoffset() == timedelta(0)
    with pytest.raises(ValueError):
        UtcTimestamp(datetime(2026, 9, 6))
    with pytest.raises(ValueError):
        UtcTimestamp(datetime(2026, 9, 6, tzinfo=timezone(timedelta(hours=7))))
