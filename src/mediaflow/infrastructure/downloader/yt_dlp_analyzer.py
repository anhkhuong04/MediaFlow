"""yt-dlp URL analysis adapter with strict metadata normalization."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Protocol, cast

from yt_dlp import YoutubeDL  # type: ignore[import-untyped]
from yt_dlp.utils import DownloadCancelled, DownloadError  # type: ignore[import-untyped]

from mediaflow.application import AnalysisOutcome, CancellationToken
from mediaflow.domain import (
    Failure,
    FailureCategory,
    MediaInfo,
    MediaStream,
    PlaylistSummary,
    SourceUrl,
    StreamKind,
)


class MetadataNormalizationError(ValueError):
    """yt-dlp returned no usable normalized media or playlist data."""


class AnalysisDiagnostic(RuntimeError):
    """Sanitized adapter error whose chained cause stays inside infrastructure."""

    def __init__(self, failure: Failure) -> None:
        self.failure = failure
        super().__init__(failure.code)


class AnalysisDiagnosticSink(Protocol):
    def report(self, diagnostic: AnalysisDiagnostic) -> None: ...


class YtDlpSession(Protocol):
    def __enter__(self) -> YtDlpSession: ...

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object | None,
    ) -> bool | None: ...

    def extract_info(self, url: str, *, download: bool) -> object: ...


type YtDlpFactory = Callable[[Mapping[str, object]], YtDlpSession]


def _create_session(parameters: Mapping[str, object]) -> YtDlpSession:
    return cast(YtDlpSession, YoutubeDL(dict(parameters)))


@dataclass(frozen=True, slots=True)
class YtDlpAnalyzerOptions:
    """Bounds analysis I/O without pretending a socket timeout is a total deadline."""

    socket_timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        if self.socket_timeout_seconds <= 0:
            raise ValueError("Socket timeout must be positive")


@dataclass(frozen=True, slots=True)
class _SilentYtDlpLogger:
    """Prevent engine messages, including raw URLs, from reaching stderr or logs."""

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
    def report(self, diagnostic: AnalysisDiagnostic) -> None:
        del diagnostic


@dataclass(frozen=True, slots=True)
class YtDlpAnalyzer:
    """Analyze one URL synchronously; callers schedule this away from the UI thread.

    Cancellation is checked before and after extraction and through yt-dlp's
    ``match_filter`` callback. The socket timeout bounds each unresponsive network
    operation; it is intentionally not documented as a whole-operation deadline.
    """

    options: YtDlpAnalyzerOptions = YtDlpAnalyzerOptions()
    client_factory: YtDlpFactory = _create_session
    diagnostics: AnalysisDiagnosticSink = _DiscardDiagnostics()

    def analyze(self, source_url: SourceUrl, *, cancellation: CancellationToken) -> AnalysisOutcome:
        if cancellation.is_cancelled():
            return _cancelled_outcome()

        def cancel_filter(info: object, *, incomplete: bool = False) -> None:
            del info, incomplete
            if cancellation.is_cancelled():
                raise DownloadCancelled("MediaFlow analysis was cancelled")

        parameters: dict[str, object] = {
            "cachedir": False,
            "extract_flat": "in_playlist",
            "logger": _SilentYtDlpLogger(),
            "match_filter": cancel_filter,
            "no_warnings": True,
            "noplaylist": False,
            "quiet": True,
            "skip_download": True,
            "socket_timeout": self.options.socket_timeout_seconds,
        }
        try:
            with self.client_factory(parameters) as client:
                raw_metadata = client.extract_info(str(source_url), download=False)
            if cancellation.is_cancelled():
                return _cancelled_outcome()
            return AnalysisOutcome.succeeded(normalize_metadata(raw_metadata, source_url))
        except DownloadCancelled as error:
            failure = Failure(FailureCategory.CANCELLED, "analysis.cancelled", retryable=False)
            self._report(failure, error)
            return AnalysisOutcome.failed(failure)
        except DownloadError as error:
            failure = map_ytdlp_error(error)
            self._report(failure, error)
            return AnalysisOutcome.failed(failure)
        except (MetadataNormalizationError, TypeError, ValueError) as error:
            failure = Failure(
                FailureCategory.UNEXPECTED, "analysis.invalid_metadata", retryable=False
            )
            self._report(failure, error)
            return AnalysisOutcome.failed(failure)
        except Exception as error:
            failure = Failure(FailureCategory.UNEXPECTED, "analysis.unexpected", retryable=False)
            self._report(failure, error)
            return AnalysisOutcome.failed(failure)

    def _report(self, failure: Failure, cause: Exception) -> None:
        diagnostic = AnalysisDiagnostic(failure)
        diagnostic.__cause__ = cause
        self.diagnostics.report(diagnostic)


def normalize_metadata(raw_metadata: object, requested_url: SourceUrl) -> MediaInfo:
    """Convert yt-dlp's untrusted dictionary into a typed domain value."""

    raw = _as_mapping(raw_metadata)
    if raw is None:
        raise MetadataNormalizationError("yt-dlp metadata must be a mapping")

    playlist = _normalize_playlist(raw)
    streams = _normalize_streams(raw)
    if not streams and playlist is None:
        raise MetadataNormalizationError("yt-dlp metadata contains no usable streams")

    return MediaInfo(
        source_url=requested_url,
        canonical_url=_url_or_none(raw.get("webpage_url")),
        title=_text(raw.get("title")) or _text(raw.get("fulltitle")) or "Untitled media",
        source_name=(
            _text(raw.get("extractor_key")) or _text(raw.get("extractor")) or "Unknown source"
        ),
        streams=streams,
        uploader=_text(raw.get("uploader")) or _text(raw.get("channel")),
        duration_seconds=_nonnegative_number(raw.get("duration")),
        thumbnail_url=_url_or_none(raw.get("thumbnail")),
        is_live=_is_live(raw),
        has_subtitles=_has_nonempty_mapping(raw.get("subtitles")),
        has_automatic_captions=_has_nonempty_mapping(raw.get("automatic_captions")),
        chapter_count=_chapter_count(raw.get("chapters")),
        playlist=playlist,
    )


def map_ytdlp_error(error: DownloadError) -> Failure:
    """Classify engine text locally; the text itself never crosses the adapter."""

    detail = str(error).casefold()
    if _contains(detail, "unsupported url", "no suitable extractor"):
        return Failure(
            FailureCategory.UNSUPPORTED_SOURCE, "analysis.unsupported_source", retryable=False
        )
    if _contains(
        detail,
        "sign in",
        "sign-in",
        "login required",
        "log in",
        "authentication required",
        "cookies-from-browser",
        "http error 401",
        "private video",
        "this video is private",
    ):
        return Failure(FailureCategory.AUTH_REQUIRED, "analysis.auth_required", retryable=False)
    if _contains(
        detail,
        "http error 403",
        "forbidden",
        "access denied",
        "not permitted",
        "not available in your country",
        "geo-restricted",
        "geographic restriction",
    ):
        return Failure(FailureCategory.ACCESS_DENIED, "analysis.access_denied", retryable=False)
    if _contains(
        detail,
        "video unavailable",
        "media unavailable",
        "has been removed",
        "no longer available",
        "does not exist",
    ):
        return Failure(
            FailureCategory.MEDIA_UNAVAILABLE, "analysis.media_unavailable", retryable=False
        )
    if _contains(
        detail,
        "timed out",
        "timeout",
        "connection reset",
        "connection refused",
        "temporary failure",
        "name resolution",
        "network is unreachable",
    ):
        return Failure(FailureCategory.NETWORK, "analysis.network", retryable=True)
    return Failure(FailureCategory.UNEXPECTED, "analysis.engine_error", retryable=False)


def _cancelled_outcome() -> AnalysisOutcome:
    return AnalysisOutcome.failed(
        Failure(FailureCategory.CANCELLED, "analysis.cancelled", retryable=False)
    )


def _normalize_streams(raw: Mapping[str, object]) -> tuple[MediaStream, ...]:
    formats = raw.get("formats")
    candidates: Sequence[object]
    if isinstance(formats, Sequence) and not isinstance(formats, (str, bytes)):
        candidates = formats
    elif raw.get("format_id") is not None:
        candidates = (raw,)
    else:
        candidates = ()

    streams: list[MediaStream] = []
    seen_keys: set[str] = set()
    for candidate in candidates:
        item = _as_mapping(candidate)
        if item is None:
            continue
        key = _text(item.get("format_id"))
        if key is None or key in seen_keys:
            continue
        kind = _stream_kind(item)
        if kind is None:
            continue
        seen_keys.add(key)
        streams.append(
            MediaStream(
                key=key,
                kind=kind,
                container=_normalized_token(item.get("ext")),
                video_codec=_codec(item.get("vcodec")),
                audio_codec=_codec(item.get("acodec")),
                width_pixels=_positive_int(item.get("width")),
                height_pixels=_positive_int(item.get("height")),
                frames_per_second=_positive_number(item.get("fps")),
                bitrate_kilobits_per_second=_bitrate(item, kind),
                size_bytes=(
                    _positive_int(item.get("filesize"))
                    or _positive_int(item.get("filesize_approx"))
                ),
            )
        )
    return tuple(streams)


def _normalize_playlist(raw: Mapping[str, object]) -> PlaylistSummary | None:
    raw_entries = raw.get("entries")
    is_playlist = _text(raw.get("_type")) in {"playlist", "multi_video"}
    if not is_playlist and raw_entries is None:
        return None

    entries: Sequence[object] | None = None
    if isinstance(raw_entries, Sequence) and not isinstance(raw_entries, (str, bytes)):
        entries = raw_entries
    available = (
        sum(_as_mapping(entry) is not None for entry in entries) if entries is not None else None
    )
    declared = _nonnegative_int(raw.get("playlist_count"))
    if declared is not None and available is not None:
        item_count = max(declared, available)
    elif declared is not None:
        item_count = declared
    elif entries is not None:
        item_count = len(entries)
    else:
        item_count = None
    return PlaylistSummary(item_count=item_count, available_item_count=available)


def _stream_kind(item: Mapping[str, object]) -> StreamKind | None:
    has_video = _codec(item.get("vcodec")) is not None
    has_audio = _codec(item.get("acodec")) is not None
    if has_video and has_audio:
        return StreamKind.AUDIO_VIDEO
    if has_video:
        return StreamKind.VIDEO
    if has_audio:
        return StreamKind.AUDIO
    return None


def _codec(value: object) -> str | None:
    codec = _normalized_token(value)
    return None if codec is None or codec.casefold() == "none" else codec


def _bitrate(item: Mapping[str, object], kind: StreamKind) -> float | None:
    candidates = ("abr", "tbr") if kind is StreamKind.AUDIO else ("vbr", "tbr")
    for key in candidates:
        value = _positive_number(item.get(key))
        if value is not None:
            return value
    return None


def _is_live(raw: Mapping[str, object]) -> bool:
    value = raw.get("is_live")
    if isinstance(value, bool):
        return value
    return _text(raw.get("live_status")) in {"is_live", "is_upcoming"}


def _chapter_count(value: object) -> int:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return 0
    return sum(_as_mapping(chapter) is not None for chapter in value)


def _has_nonempty_mapping(value: object) -> bool:
    mapping = _as_mapping(value)
    return mapping is not None and bool(mapping)


def _url_or_none(value: object) -> SourceUrl | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return SourceUrl(text)
    except ValueError:
        return None


def _normalized_token(value: object) -> str | None:
    text = _text(value)
    return text.casefold() if text is not None else None


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _positive_number(value: object) -> float | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
        or value <= 0
    ):
        return None
    return float(value)


def _nonnegative_number(value: object) -> float | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
        or value < 0
    ):
        return None
    return float(value)


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _as_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    if not all(isinstance(key, str) for key in value):
        return None
    return cast(Mapping[str, object], value)


def _contains(value: str, *needles: str) -> bool:
    return any(needle in value for needle in needles)
