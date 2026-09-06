"""Application-owned logging with an allowlist at the final serialization boundary.

Do not attach third-party loggers to this handler. Unknown messages are suppressed,
and arbitrary args, exception text, stack traces and extras are never serialized.
"""

import json
import logging
import sys
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import UUID

_MESSAGES = {
    "application.started": "Ứng dụng đã khởi động",
    "application.stopped": "Ứng dụng đã dừng",
    "application.failed": "Ứng dụng gặp lỗi",
}


class _SafeRotatingFileHandler(RotatingFileHandler):
    def handleError(self, record: logging.LogRecord) -> None:
        # The stdlib fallback prints the original message/args on write failure.
        # Never pass the untrusted record to that fallback.
        sys.stderr.write("MediaFlow logging unavailable; check the log directory.\n")


class _SafeFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Never call getMessage(): formatting user objects can expose secret data.
        event = record.msg if type(record.msg) is str else "suppressed"
        if event not in _MESSAGES:
            event = "suppressed"
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": {
                logging.DEBUG: "DEBUG",
                logging.INFO: "INFO",
                logging.WARNING: "WARNING",
                logging.ERROR: "ERROR",
                logging.CRITICAL: "CRITICAL",
            }.get(record.levelno, "UNKNOWN"),
            "event": event,
            "message": _MESSAGES.get(event, "Unstructured log entry suppressed"),
        }
        task_id = getattr(record, "task_id", None)
        if type(task_id) is UUID:
            payload["task_id"] = str(task_id)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(
    directory: Path,
    *,
    max_bytes: int = 2 * 1024 * 1024,
    backup_count: int = 3,
) -> logging.Logger:
    """Configure the mediaflow logger at startup, before starting workers.

    The caller supplies a local application-data directory. Reconfiguration replaces
    and closes owned handlers. Call shutdown_logging after workers have stopped.
    Filesystem errors propagate so the caller can report initialization failure.
    """
    if max_bytes <= 0 or backup_count < 1:
        raise ValueError("Rotation requires positive max_bytes and backup_count")
    directory.mkdir(parents=True, exist_ok=True)
    handler = _SafeRotatingFileHandler(
        directory / "mediaflow.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(_SafeFormatter())
    logger = logging.getLogger("mediaflow")
    shutdown_logging()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def shutdown_logging() -> None:
    """Close application-owned log files; leave the root logger untouched."""
    logger = logging.getLogger("mediaflow")
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
