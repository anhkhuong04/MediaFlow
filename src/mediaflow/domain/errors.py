"""Stable failure values exposed by the domain and application layers."""

import re
from dataclasses import dataclass
from enum import StrEnum

_FAILURE_CODE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


class FailureCategory(StrEnum):
    INVALID_INPUT = "invalid_input"
    UNSUPPORTED_SOURCE = "unsupported_source"
    MEDIA_UNAVAILABLE = "media_unavailable"
    AUTH_REQUIRED = "auth_required"
    ACCESS_DENIED = "access_denied"
    NETWORK = "network"
    DISK_SPACE = "disk_space"
    DEPENDENCY = "dependency"
    OUTPUT_CONFLICT = "output_conflict"
    DOWNLOAD = "download"
    PROCESSING = "processing"
    CANCELLED = "cancelled"
    UNEXPECTED = "unexpected"


@dataclass(frozen=True, slots=True)
class Failure:
    """A sanitized machine-readable failure; raw third-party details stay outside it."""

    category: FailureCategory
    code: str
    retryable: bool

    def __post_init__(self) -> None:
        if _FAILURE_CODE.fullmatch(self.code) is None:
            raise ValueError("Failure code must be a stable lowercase identifier")
