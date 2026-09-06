"""Normalized media metadata and user-facing download presets."""

from dataclasses import dataclass
from enum import StrEnum

from mediaflow.domain.identifiers import SourceUrl


class StreamKind(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"
    AUDIO_VIDEO = "audio_video"


class VideoQuality(StrEnum):
    BEST = "best"
    P2160 = "2160p"
    P1440 = "1440p"
    P1080 = "1080p"
    P720 = "720p"


class VideoContainer(StrEnum):
    MP4 = "mp4"
    MKV = "mkv"


class AudioQuality(StrEnum):
    BEST = "best"


class AudioContainer(StrEnum):
    ORIGINAL = "original"
    M4A = "m4a"
    MP3 = "mp3"


@dataclass(frozen=True, slots=True)
class PlaylistSummary:
    """Counts for a playlist container without leaking its raw entries."""

    item_count: int | None
    available_item_count: int | None

    def __post_init__(self) -> None:
        if self.item_count is not None and self.item_count < 0:
            raise ValueError("Playlist item count cannot be negative")
        if self.available_item_count is not None and self.available_item_count < 0:
            raise ValueError("Available playlist item count cannot be negative")
        if (
            self.item_count is not None
            and self.available_item_count is not None
            and self.available_item_count > self.item_count
        ):
            raise ValueError("Available playlist items cannot exceed total items")


@dataclass(frozen=True, slots=True)
class MediaStream:
    """A normalized stream; ``key`` is opaque outside the downloader adapter."""

    key: str
    kind: StreamKind
    container: str | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    width_pixels: int | None = None
    height_pixels: int | None = None
    frames_per_second: float | None = None
    bitrate_kilobits_per_second: float | None = None
    size_bytes: int | None = None

    def __post_init__(self) -> None:
        if not self.key or self.key != self.key.strip():
            raise ValueError("Stream key must be non-empty and normalized")
        for name in ("container", "video_codec", "audio_codec"):
            value = getattr(self, name)
            if value is not None and (not value or value != value.strip()):
                raise ValueError(f"{name} must be non-empty and normalized when present")
        _require_positive("width_pixels", self.width_pixels)
        _require_positive("height_pixels", self.height_pixels)
        _require_positive("frames_per_second", self.frames_per_second)
        _require_positive("bitrate_kilobits_per_second", self.bitrate_kilobits_per_second)
        _require_positive("size_bytes", self.size_bytes)


@dataclass(frozen=True, slots=True)
class MediaInfo:
    source_url: SourceUrl
    title: str
    source_name: str
    streams: tuple[MediaStream, ...]
    canonical_url: SourceUrl | None = None
    uploader: str | None = None
    duration_seconds: float | None = None
    thumbnail_url: SourceUrl | None = None
    is_live: bool = False
    has_subtitles: bool = False
    has_automatic_captions: bool = False
    chapter_count: int = 0
    playlist: PlaylistSummary | None = None

    def __post_init__(self) -> None:
        if not self.title or not self.title.strip():
            raise ValueError("Media title must be non-empty")
        if not self.source_name or not self.source_name.strip():
            raise ValueError("Media source name must be non-empty")
        object.__setattr__(self, "streams", tuple(self.streams))
        if not self.streams and self.playlist is None:
            raise ValueError("Single media info must contain at least one normalized stream")
        if self.uploader is not None and not self.uploader.strip():
            raise ValueError("Uploader must be non-empty when present")
        if self.duration_seconds is not None and self.duration_seconds < 0:
            raise ValueError("Duration cannot be negative")
        if self.chapter_count < 0:
            raise ValueError("Chapter count cannot be negative")


@dataclass(frozen=True, slots=True)
class VideoPreset:
    quality: VideoQuality = VideoQuality.BEST
    container: VideoContainer = VideoContainer.MP4
    preferred_frames_per_second: int | None = None

    def __post_init__(self) -> None:
        _require_positive("preferred_frames_per_second", self.preferred_frames_per_second)


@dataclass(frozen=True, slots=True)
class AudioPreset:
    quality: AudioQuality = AudioQuality.BEST
    container: AudioContainer = AudioContainer.ORIGINAL


type DownloadPreset = VideoPreset | AudioPreset


def _require_positive(name: str, value: int | float | None) -> None:
    if value is not None and value <= 0:
        raise ValueError(f"{name} must be positive when present")
