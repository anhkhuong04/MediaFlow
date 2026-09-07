"""yt-dlp download adapter with typed progress, failures, and staging files."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Protocol, cast

from yt_dlp import YoutubeDL  # type: ignore[import-untyped]
from yt_dlp.utils import DownloadCancelled, DownloadError  # type: ignore[import-untyped]

from mediaflow.application import (
    CancellationToken,
    DownloadArtifact,
    DownloadJob,
    DownloadOutcome,
    PartialFilePolicy,
    ProgressSink,
)
from mediaflow.domain import (
    Failure,
    FailureCategory,
    OutputPath,
    ProgressSnapshot,
    StreamKind,
    UtcTimestamp,
)
from mediaflow.infrastructure.downloader.format_selection import build_format_selection
from mediaflow.infrastructure.filesystem.staging_recovery import write_artifact_manifest

_LOGGER = logging.getLogger("mediaflow.download")


class DownloadDiagnostic(RuntimeError):
    """Sanitized adapter error whose raw cause remains infrastructure-local."""

    def __init__(self, failure: Failure) -> None:
        self.failure = failure
        super().__init__(failure.code)


class DownloadDiagnosticSink(Protocol):
    def report(self, diagnostic: DownloadDiagnostic) -> None: ...


class YtDlpDownloadSession(Protocol):
    def __enter__(self) -> YtDlpDownloadSession: ...

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object | None,
    ) -> bool | None: ...

    def extract_info(self, url: str, *, download: bool) -> object: ...


type YtDlpDownloadFactory = Callable[[Mapping[str, object]], YtDlpDownloadSession]


def _create_session(parameters: Mapping[str, object]) -> YtDlpDownloadSession:
    return cast(YtDlpDownloadSession, YoutubeDL(dict(parameters)))


@dataclass(frozen=True, slots=True)
class YtDlpDownloaderOptions:
    """Execution policy for downloads and recoverable staging data."""

    socket_timeout_seconds: float = 15.0
    partial_file_policy: PartialFilePolicy = PartialFilePolicy.KEEP

    def __post_init__(self) -> None:
        if self.socket_timeout_seconds <= 0:
            raise ValueError("Socket timeout must be positive")
        if self.partial_file_policy is not PartialFilePolicy.KEEP:
            raise ValueError("C5 only supports retaining partial files")


@dataclass(frozen=True, slots=True)
class _SilentYtDlpLogger:
    def debug(self, message: str) -> None:
        del message

    def info(self, message: str) -> None:
        del message

    def warning(self, message: str) -> None:
        del message

    def error(self, message: str) -> None:
        del message


@dataclass(frozen=True, slots=True)
class _DiscardDiagnostics:
    def report(self, diagnostic: DownloadDiagnostic) -> None:
        del diagnostic


@dataclass(frozen=True, slots=True)
class YtDlpDownloader:
    """Download immutable jobs synchronously into an attempt-specific directory.

    QueueManager invokes this adapter on its bounded worker pool. yt-dlp partial
    files are deliberately retained after cancellation or failure. Automatic
    merging is disabled so C6 can process and verify outputs before completion.
    """

    options: YtDlpDownloaderOptions = YtDlpDownloaderOptions()
    client_factory: YtDlpDownloadFactory = _create_session
    diagnostics: DownloadDiagnosticSink = _DiscardDiagnostics()
    timestamp_factory: Callable[[], UtcTimestamp] = UtcTimestamp.now

    def download(
        self,
        job: DownloadJob,
        *,
        progress: ProgressSink,
        cancellation: CancellationToken,
    ) -> DownloadOutcome:
        if cancellation.is_cancelled():
            return _cancelled_outcome()

        staging_directory = (
            job.request.output_directory.value
            / ".mediaflow-staging"
            / str(job.task_id)
            / str(job.attempt_id)
        )
        try:
            staging_directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            failure = _map_os_error(error)
            self._report(failure, error)
            return DownloadOutcome.failed(failure)

        selection = build_format_selection(job.request.preset)

        def cancel_filter(info: object, *, incomplete: bool = False) -> None:
            del info, incomplete
            if cancellation.is_cancelled():
                raise DownloadCancelled("MediaFlow download was cancelled")

        def progress_hook(raw: object) -> None:
            if cancellation.is_cancelled():
                raise DownloadCancelled("MediaFlow download was cancelled")
            snapshot = normalize_download_progress(raw, captured_at=self.timestamp_factory())
            if snapshot is None:
                return
            try:
                progress.report(snapshot)
            except Exception:
                # Observers are non-authoritative and cannot abort engine work.
                _LOGGER.warning("application.failed")

        parameters: dict[str, object] = {
            # This yt-dlp switch also prevents its implicit FFmpeg merge. The
            # selector remains preset-owned and C6 handles processing explicitly.
            "allow_unplayable_formats": True,
            "cachedir": False,
            "continuedl": True,
            "format": selection.format_selector,
            "logger": _SilentYtDlpLogger(),
            "match_filter": cancel_filter,
            "no_warnings": True,
            "nopart": False,
            "noplaylist": True,
            "outtmpl": str(staging_directory / "%(title).160B [%(id)s].%(ext)s"),
            "overwrites": False,
            "progress_hooks": [progress_hook],
            "quiet": True,
            "socket_timeout": self.options.socket_timeout_seconds,
            "windowsfilenames": True,
        }
        try:
            with self.client_factory(parameters) as client:
                raw_result = client.extract_info(str(job.request.source_url), download=True)
            if cancellation.is_cancelled():
                return _cancelled_outcome()
            artifact = _normalize_artifact(
                raw_result,
                staging_directory=staging_directory,
                requires_processing=selection.extract_audio
                or selection.output_container is not None,
            )
            write_artifact_manifest(staging_directory, artifact)
            return DownloadOutcome.succeeded(artifact)
        except DownloadCancelled as error:
            failure = _cancelled_failure()
            self._report(failure, error)
            return DownloadOutcome.failed(failure)
        except DownloadError as error:
            failure = (
                _cancelled_failure()
                if cancellation.is_cancelled()
                else map_ytdlp_download_error(error)
            )
            self._report(failure, error)
            return DownloadOutcome.failed(failure)
        except OSError as error:
            failure = _map_os_error(error)
            self._report(failure, error)
            return DownloadOutcome.failed(failure)
        except (TypeError, ValueError) as error:
            failure = Failure(
                FailureCategory.UNEXPECTED,
                "download.invalid_result",
                retryable=False,
            )
            self._report(failure, error)
            return DownloadOutcome.failed(failure)
        except Exception as error:
            failure = Failure(FailureCategory.UNEXPECTED, "download.unexpected", retryable=False)
            self._report(failure, error)
            return DownloadOutcome.failed(failure)

    def _report(self, failure: Failure, cause: Exception) -> None:
        diagnostic = DownloadDiagnostic(failure)
        diagnostic.__cause__ = cause
        try:
            self.diagnostics.report(diagnostic)
        except Exception:
            _LOGGER.warning("application.failed")


def normalize_download_progress(
    raw_progress: object, *, captured_at: UtcTimestamp
) -> ProgressSnapshot | None:
    """Normalize a yt-dlp progress hook without inventing unknown totals."""

    raw = _as_mapping(raw_progress)
    if raw is None or raw.get("status") not in {"downloading", "finished"}:
        return None
    downloaded = _nonnegative_int(raw.get("downloaded_bytes"))
    total = _positive_int(raw.get("total_bytes")) or _positive_int(raw.get("total_bytes_estimate"))
    if raw.get("status") == "finished" and downloaded is None:
        downloaded = total
    if downloaded is None:
        return None
    return ProgressSnapshot.downloading(
        captured_at=captured_at,
        downloaded_bytes=downloaded,
        total_bytes=total,
        speed_bytes_per_second=_nonnegative_number(raw.get("speed")),
        eta_seconds=_nonnegative_number(raw.get("eta")),
    )


def map_ytdlp_download_error(error: DownloadError) -> Failure:
    """Map raw engine errors to sanitized download-stage failures."""

    detail = str(error).casefold()
    if _contains(detail, "no space left", "disk full", "not enough space"):
        return Failure(FailureCategory.DISK_SPACE, "download.disk_space", retryable=True)
    if _contains(detail, "file exists", "already exists", "unable to overwrite"):
        return Failure(
            FailureCategory.OUTPUT_CONFLICT,
            "download.output_conflict",
            retryable=False,
        )
    if _contains(detail, "sign in", "login required", "private video", "http error 401"):
        return Failure(FailureCategory.AUTH_REQUIRED, "download.auth_required", retryable=False)
    if _contains(detail, "http error 403", "forbidden", "access denied", "geo-restricted"):
        return Failure(FailureCategory.ACCESS_DENIED, "download.access_denied", retryable=False)
    if _contains(detail, "unavailable", "has been removed", "does not exist"):
        return Failure(
            FailureCategory.MEDIA_UNAVAILABLE,
            "download.media_unavailable",
            retryable=False,
        )
    if _contains(
        detail,
        "timed out",
        "timeout",
        "connection reset",
        "connection refused",
        "network is unreachable",
        "temporary failure",
    ):
        return Failure(FailureCategory.NETWORK, "download.network", retryable=True)
    return Failure(FailureCategory.DOWNLOAD, "download.engine_error", retryable=True)


def _normalize_artifact(
    raw_result: object, *, staging_directory: Path, requires_processing: bool
) -> DownloadArtifact:
    raw = _as_mapping(raw_result)
    if raw is None:
        raise ValueError("yt-dlp result must be a mapping")
    candidates: list[tuple[object, StreamKind | None]] = []
    requested = raw.get("requested_downloads")
    if isinstance(requested, Sequence) and not isinstance(requested, (str, bytes)):
        for item in requested:
            mapping = _as_mapping(item)
            if mapping is not None:
                kind = _artifact_stream_kind(mapping)
                candidates.extend(
                    ((mapping.get("filepath"), kind), (mapping.get("_filename"), kind))
                )
    root_kind = _artifact_stream_kind(raw)
    candidates.extend(((raw.get("filepath"), root_kind), (raw.get("_filename"), root_kind)))

    staging_root = staging_directory.resolve(strict=False)
    paths: list[OutputPath] = []
    kinds: list[StreamKind | None] = []
    seen: set[Path] = set()
    for candidate, kind in candidates:
        if not isinstance(candidate, str) or not candidate.strip():
            continue
        path = Path(candidate).resolve(strict=False)
        if not path.is_relative_to(staging_root):
            raise ValueError("yt-dlp returned a path outside the attempt staging directory")
        if path not in seen:
            seen.add(path)
            paths.append(OutputPath(path))
            kinds.append(kind)
    normalized_kinds = tuple(kinds) if kinds and all(kind is not None for kind in kinds) else ()
    return DownloadArtifact(
        tuple(paths),
        requires_processing=requires_processing,
        stream_kinds=cast(tuple[StreamKind, ...], normalized_kinds),
    )


def _artifact_stream_kind(raw: Mapping[str, object]) -> StreamKind | None:
    video = isinstance(raw.get("vcodec"), str) and raw.get("vcodec") != "none"
    audio = isinstance(raw.get("acodec"), str) and raw.get("acodec") != "none"
    if video and audio:
        return StreamKind.AUDIO_VIDEO
    if video:
        return StreamKind.VIDEO
    if audio:
        return StreamKind.AUDIO
    return None


def _map_os_error(error: OSError) -> Failure:
    if error.errno == 28:
        return Failure(FailureCategory.DISK_SPACE, "download.disk_space", retryable=True)
    return Failure(FailureCategory.DOWNLOAD, "download.filesystem", retryable=True)


def _cancelled_failure() -> Failure:
    return Failure(FailureCategory.CANCELLED, "download.cancelled", retryable=False)


def _cancelled_outcome() -> DownloadOutcome:
    return DownloadOutcome.failed(_cancelled_failure())


def _as_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        return None
    return cast(Mapping[str, object], value)


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _nonnegative_number(value: object) -> float | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
        or value < 0
    ):
        return None
    return float(value)


def _contains(value: str, *needles: str) -> bool:
    return any(needle in value for needle in needles)
