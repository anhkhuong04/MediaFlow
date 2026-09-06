import json
import logging
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest

from mediaflow.logging_setup import configure_logging, shutdown_logging


@pytest.fixture(autouse=True)
def close_logs() -> Iterator[None]:
    yield
    shutdown_logging()


def test_utf8_and_safe_context(tmp_path: Path) -> None:
    logger = configure_logging(tmp_path)
    task_id = UUID("d14f0456-62a9-4526-aa25-f001ed037052")
    logger.info("application.started", extra={"task_id": task_id})
    entry = json.loads((tmp_path / "mediaflow.log").read_text(encoding="utf-8"))
    assert entry["message"] == "Ứng dụng đã khởi động"
    assert entry["task_id"] == str(task_id)
    assert entry["timestamp"].endswith("+00:00")


def test_untrusted_data_is_not_serialized(tmp_path: Path) -> None:
    logger = configure_logging(tmp_path)
    secret = "private-session-123"
    logger.warning("Authorization: Bearer %s", secret)
    logger.info({"cookie": secret})
    try:
        raise ValueError(secret)
    except ValueError:
        logger.exception(
            "application.failed", extra={"cookie": secret, "task_id": secret}, stack_info=True
        )
    content = (tmp_path / "mediaflow.log").read_text(encoding="utf-8")
    assert secret not in content
    assert "Traceback" not in content
    assert [json.loads(line)["event"] for line in content.splitlines()] == [
        "suppressed",
        "suppressed",
        "application.failed",
    ]


def test_rotation_and_reconfiguration_release_files(tmp_path: Path) -> None:
    root_handlers = logging.getLogger().handlers[:]
    logger = configure_logging(tmp_path, max_bytes=250, backup_count=2)
    for _ in range(10):
        logger.info("application.started")
    assert len(list(tmp_path.glob("mediaflow.log*"))) == 3
    configure_logging(tmp_path)
    assert len(logger.handlers) == 1
    assert logger.propagate is False
    shutdown_logging()
    for path in tmp_path.iterdir():
        path.unlink()  # Windows rejects this if the old file handle remains open.
    assert logging.getLogger().handlers == root_handlers


def test_write_failure_does_not_dump_raw_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    logger = configure_logging(tmp_path, max_bytes=1)
    logger.info("application.started")

    def fail_rotation() -> None:
        raise OSError("private-filesystem-detail")

    monkeypatch.setattr(logger.handlers[0], "doRollover", fail_rotation)
    logger.error("cookie=private-cookie")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "MediaFlow logging unavailable; check the log directory.\n"


@pytest.mark.parametrize(("max_bytes", "backup_count"), [(0, 1), (10, 0), (-1, 2)])
def test_invalid_rotation_does_not_create_files(
    tmp_path: Path, max_bytes: int, backup_count: int
) -> None:
    with pytest.raises(ValueError):
        configure_logging(tmp_path, max_bytes=max_bytes, backup_count=backup_count)
    assert list(tmp_path.iterdir()) == []
