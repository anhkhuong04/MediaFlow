"""Typed identifiers and boundary values shared by the domain."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class TaskId:
    value: UUID

    def __post_init__(self) -> None:
        if self.value.int == 0:
            raise ValueError("Task ID must not be the nil UUID")

    @classmethod
    def new(cls) -> "TaskId":
        return cls(uuid4())

    @classmethod
    def parse(cls, value: str) -> "TaskId":
        return cls(UUID(value))

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class AttemptId:
    value: UUID

    def __post_init__(self) -> None:
        if self.value.int == 0:
            raise ValueError("Attempt ID must not be the nil UUID")

    @classmethod
    def new(cls) -> "AttemptId":
        return cls(uuid4())

    @classmethod
    def parse(cls, value: str) -> "AttemptId":
        return cls(UUID(value))

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class SourceUrl:
    value: str

    def __post_init__(self) -> None:
        if not self.value or self.value != self.value.strip():
            raise ValueError("Source URL must be non-empty and cannot have surrounding whitespace")
        if any(ord(character) < 32 for character in self.value):
            raise ValueError("Source URL cannot contain control characters")
        try:
            parsed = urlsplit(self.value)
            hostname = parsed.hostname
            _validated_port = parsed.port  # Validate malformed and out-of-range ports.
        except ValueError as error:
            raise ValueError("Source URL is malformed") from error
        if parsed.scheme.lower() not in {"http", "https"} or hostname is None:
            raise ValueError("Source URL must be an absolute HTTP or HTTPS URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("Source URL cannot contain embedded credentials")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class OutputPath:
    """An absolute path selected by the user; existence is an adapter concern."""

    value: Path

    def __post_init__(self) -> None:
        if not self.value.is_absolute():
            raise ValueError("Output path must be absolute")

    def __fspath__(self) -> str:
        return str(self.value)

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True, order=True)
class UtcTimestamp:
    value: datetime

    def __post_init__(self) -> None:
        if self.value.tzinfo is None or self.value.utcoffset() != timedelta(0):
            raise ValueError("Timestamp must be timezone-aware UTC")

    @classmethod
    def now(cls) -> "UtcTimestamp":
        return cls(datetime.now(UTC))
