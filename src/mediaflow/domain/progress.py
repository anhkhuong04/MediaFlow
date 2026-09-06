"""Progress snapshots with explicit units and honest unknown values."""

from dataclasses import dataclass
from enum import StrEnum
from math import isclose

from mediaflow.domain.identifiers import UtcTimestamp


class ProgressStage(StrEnum):
    DOWNLOADING = "downloading"
    PROCESSING = "processing"


@dataclass(frozen=True, slots=True)
class ProgressSnapshot:
    stage: ProgressStage
    captured_at: UtcTimestamp
    fraction: float | None = None
    downloaded_bytes: int | None = None
    total_bytes: int | None = None
    speed_bytes_per_second: float | None = None
    eta_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.fraction is not None and not 0 <= self.fraction <= 1:
            raise ValueError("Progress fraction must be between zero and one")
        _require_non_negative("downloaded_bytes", self.downloaded_bytes)
        if self.total_bytes is not None and self.total_bytes <= 0:
            raise ValueError("total_bytes must be positive when present")
        _require_non_negative("speed_bytes_per_second", self.speed_bytes_per_second)
        _require_non_negative("eta_seconds", self.eta_seconds)
        if self.total_bytes is not None and self.downloaded_bytes is None:
            raise ValueError("total_bytes requires downloaded_bytes")
        if (
            self.downloaded_bytes is not None
            and self.total_bytes is not None
            and self.fraction is not None
        ):
            expected_fraction = min(self.downloaded_bytes / self.total_bytes, 1.0)
            if not isclose(self.fraction, expected_fraction, abs_tol=1e-9):
                raise ValueError("fraction must agree with byte progress")

    @classmethod
    def downloading(
        cls,
        *,
        captured_at: UtcTimestamp,
        downloaded_bytes: int,
        total_bytes: int | None = None,
        speed_bytes_per_second: float | None = None,
        eta_seconds: float | None = None,
    ) -> "ProgressSnapshot":
        fraction = None
        if total_bytes is not None and total_bytes > 0:
            fraction = min(downloaded_bytes / total_bytes, 1.0)
        return cls(
            stage=ProgressStage.DOWNLOADING,
            captured_at=captured_at,
            fraction=fraction,
            downloaded_bytes=downloaded_bytes,
            total_bytes=total_bytes,
            speed_bytes_per_second=speed_bytes_per_second,
            eta_seconds=eta_seconds,
        )

    @classmethod
    def processing(
        cls, *, captured_at: UtcTimestamp, fraction: float | None = None
    ) -> "ProgressSnapshot":
        return cls(stage=ProgressStage.PROCESSING, captured_at=captured_at, fraction=fraction)


def _require_non_negative(name: str, value: int | float | None) -> None:
    if value is not None and value < 0:
        raise ValueError(f"{name} cannot be negative")
