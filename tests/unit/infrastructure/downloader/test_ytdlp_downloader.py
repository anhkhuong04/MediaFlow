from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import nan
from pathlib import Path

import pytest
from yt_dlp.utils import DownloadError  # type: ignore[import-untyped]

from mediaflow.application import DownloadJob, PartialFilePolicy
from mediaflow.domain import (
    AttemptId,
    DownloadRequest,
    FailureCategory,
    OutputPath,
    ProgressSnapshot,
    SourceUrl,
    TaskId,
    UtcTimestamp,
    VideoPreset,
)
from mediaflow.infrastructure.downloader import (
    DownloadDiagnostic,
    YtDlpDownloader,
    YtDlpDownloaderOptions,
    map_ytdlp_download_error,
    normalize_download_progress,
)


@dataclass(slots=True)
class Token:
    cancelled: bool = False

    def is_cancelled(self) -> bool:
        return self.cancelled


@dataclass(slots=True)
class Sink:
    values: list[ProgressSnapshot] = field(default_factory=list)
    fail: bool = False

    def report(self, progress: ProgressSnapshot) -> None:
        if self.fail:
            raise RuntimeError("observer failed")
        self.values.append(progress)


@dataclass(slots=True)
class Session:
    parameters: Mapping[str, object] | None = None
    token_to_cancel: Token | None = None
    error: Exception | None = None
    outside_path: Path | None = None
    partial_path: Path | None = None

    def __enter__(self) -> "Session":
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object | None,
    ) -> bool | None:
        return None

    def extract_info(self, url: str, *, download: bool) -> object:
        assert url == "https://example.com/watch/1"
        assert download
        assert self.parameters is not None
        staging = Path(str(self.parameters["outtmpl"])).parent
        if self.partial_path is not None:
            self.partial_path.parent.mkdir(parents=True, exist_ok=True)
            self.partial_path.write_bytes(b"partial")
        if self.token_to_cancel is not None:
            self.token_to_cancel.cancelled = True
        hooks = self.parameters["progress_hooks"]
        assert isinstance(hooks, list) and callable(hooks[0])
        hooks[0](
            {
                "status": "downloading",
                "downloaded_bytes": 50,
                "total_bytes": 100,
                "speed": 25.0,
                "eta": 2.0,
            }
        )
        if self.error is not None:
            raise self.error
        return {
            "requested_downloads": [{"filepath": str(self.outside_path or staging / "video.webm")}]
        }


@dataclass(slots=True)
class Factory:
    session: Session
    calls: list[Mapping[str, object]] = field(default_factory=list)

    def __call__(self, parameters: Mapping[str, object]) -> Session:
        self.calls.append(parameters)
        self.session.parameters = parameters
        return self.session


@dataclass(slots=True)
class Diagnostics:
    values: list[DownloadDiagnostic] = field(default_factory=list)

    def report(self, diagnostic: DownloadDiagnostic) -> None:
        self.values.append(diagnostic)


@dataclass(slots=True)
class FailingDiagnostics:
    def report(self, diagnostic: DownloadDiagnostic) -> None:
        del diagnostic
        raise RuntimeError("diagnostic subscriber failed")


def test_adapter_builds_safe_reproducible_options_and_normalizes_artifact(
    tmp_path: Path,
) -> None:
    factory = Factory(Session())
    sink = Sink()
    downloader = YtDlpDownloader(
        options=YtDlpDownloaderOptions(socket_timeout_seconds=8),
        client_factory=factory,
        timestamp_factory=_timestamp,
    )

    outcome = downloader.download(_job(tmp_path), progress=sink, cancellation=Token())

    assert outcome.artifact is not None
    assert outcome.artifact.requires_processing
    assert len(outcome.artifact.paths) == 1
    assert sink.values[0].fraction == 0.5
    parameters = factory.calls[0]
    assert parameters["socket_timeout"] == 8
    assert parameters["continuedl"] is True
    assert parameters["nopart"] is False
    assert parameters["overwrites"] is False
    assert parameters["noplaylist"] is True
    assert parameters["allow_unplayable_formats"] is True
    assert "has_drm!=True" in str(parameters["format"])
    assert "cookiefile" not in parameters
    assert "cookiesfrombrowser" not in parameters
    staging = tmp_path / ".mediaflow-staging" / str(_TASK_ID) / str(_ATTEMPT_ID)
    assert outcome.artifact.paths[0].value.is_relative_to(staging)


def test_progress_callback_failure_does_not_abort_download(tmp_path: Path) -> None:
    outcome = YtDlpDownloader(
        client_factory=Factory(Session()), timestamp_factory=_timestamp
    ).download(_job(tmp_path), progress=Sink(fail=True), cancellation=Token())

    assert outcome.artifact is not None


def test_diagnostic_callback_failure_does_not_escape_adapter(tmp_path: Path) -> None:
    outcome = YtDlpDownloader(
        client_factory=Factory(Session(error=DownloadError("Connection timed out"))),
        diagnostics=FailingDiagnostics(),
        timestamp_factory=_timestamp,
    ).download(_job(tmp_path), progress=Sink(), cancellation=Token())

    assert outcome.failure is not None
    assert outcome.failure.category is FailureCategory.NETWORK


def test_cancel_is_cooperative_and_retains_partial_file(tmp_path: Path) -> None:
    token = Token()
    partial = tmp_path / ".mediaflow-staging" / str(_TASK_ID) / str(_ATTEMPT_ID) / "video.webm.part"
    diagnostics = Diagnostics()
    session = Session(token_to_cancel=token, partial_path=partial)
    outcome = YtDlpDownloader(
        client_factory=Factory(session),
        diagnostics=diagnostics,
        timestamp_factory=_timestamp,
    ).download(_job(tmp_path), progress=Sink(), cancellation=token)

    assert outcome.failure is not None
    assert outcome.failure.category is FailureCategory.CANCELLED
    assert partial.read_bytes() == b"partial"
    assert diagnostics.values[0].failure.code == "download.cancelled"


def test_path_outside_attempt_staging_is_rejected(tmp_path: Path) -> None:
    diagnostics = Diagnostics()
    outcome = YtDlpDownloader(
        client_factory=Factory(Session(outside_path=tmp_path / "outside.webm")),
        diagnostics=diagnostics,
        timestamp_factory=_timestamp,
    ).download(_job(tmp_path), progress=Sink(), cancellation=Token())

    assert outcome.failure is not None
    assert outcome.failure.code == "download.invalid_result"
    assert isinstance(diagnostics.values[0].__cause__, ValueError)


@pytest.mark.parametrize(
    ("raw", "downloaded", "total", "fraction", "speed", "eta"),
    [
        ({"status": "downloading", "downloaded_bytes": 7}, 7, None, None, None, None),
        (
            {
                "status": "downloading",
                "downloaded_bytes": 50,
                "total_bytes_estimate": 100,
                "speed": 12,
                "eta": 4,
            },
            50,
            100,
            0.5,
            12.0,
            4.0,
        ),
        (
            {
                "status": "downloading",
                "downloaded_bytes": 1,
                "total_bytes": 0,
                "speed": nan,
                "eta": -1,
            },
            1,
            None,
            None,
            None,
            None,
        ),
        ({"status": "finished", "total_bytes": 10}, 10, 10, 1.0, None, None),
    ],
)
def test_progress_normalization_preserves_unknown_values(
    raw: object,
    downloaded: int,
    total: int | None,
    fraction: float | None,
    speed: float | None,
    eta: float | None,
) -> None:
    snapshot = normalize_download_progress(raw, captured_at=_timestamp())

    assert snapshot is not None
    assert snapshot.downloaded_bytes == downloaded
    assert snapshot.total_bytes == total
    assert snapshot.fraction == fraction
    assert snapshot.speed_bytes_per_second == speed
    assert snapshot.eta_seconds == eta


@pytest.mark.parametrize("raw", [None, [], {"status": "processing"}, {"status": "finished"}])
def test_unusable_progress_is_ignored(raw: object) -> None:
    assert normalize_download_progress(raw, captured_at=_timestamp()) is None


@pytest.mark.parametrize(
    ("message", "category", "code", "retryable"),
    [
        ("No space left on device", FailureCategory.DISK_SPACE, "download.disk_space", True),
        (
            "Unable to overwrite; file exists",
            FailureCategory.OUTPUT_CONFLICT,
            "download.output_conflict",
            False,
        ),
        ("Please sign in", FailureCategory.AUTH_REQUIRED, "download.auth_required", False),
        ("HTTP Error 403", FailureCategory.ACCESS_DENIED, "download.access_denied", False),
        (
            "Video unavailable",
            FailureCategory.MEDIA_UNAVAILABLE,
            "download.media_unavailable",
            False,
        ),
        ("Connection timed out", FailureCategory.NETWORK, "download.network", True),
        ("Extractor failed", FailureCategory.DOWNLOAD, "download.engine_error", True),
    ],
)
def test_download_error_mapping_is_sanitized(
    message: str, category: FailureCategory, code: str, retryable: bool
) -> None:
    failure = map_ytdlp_download_error(DownloadError(message))
    assert (failure.category, failure.code, failure.retryable) == (category, code, retryable)


def test_options_reject_unsupported_partial_cleanup_policy() -> None:
    assert YtDlpDownloaderOptions().partial_file_policy is PartialFilePolicy.KEEP
    with pytest.raises(ValueError):
        YtDlpDownloaderOptions(socket_timeout_seconds=0)


_TASK_ID = TaskId.parse("00000000-0000-4000-8000-000000000001")
_ATTEMPT_ID = AttemptId.parse("00000000-0000-4000-8000-000000000002")


def _job(tmp_path: Path) -> DownloadJob:
    return DownloadJob(
        _TASK_ID,
        _ATTEMPT_ID,
        DownloadRequest(
            SourceUrl("https://example.com/watch/1"),
            "Media",
            VideoPreset(),
            OutputPath(tmp_path),
        ),
    )


def _timestamp() -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 9, 7, tzinfo=UTC))
