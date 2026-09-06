"""Application-owned preset availability rules for analysis and enqueue flows."""

from dataclasses import dataclass
from enum import StrEnum

from mediaflow.domain import (
    DownloadPreset,
    MediaInfo,
    StreamKind,
    VideoPreset,
    VideoQuality,
)

_QUALITY_HEIGHT = {
    VideoQuality.P2160: 2160,
    VideoQuality.P1440: 1440,
    VideoQuality.P1080: 1080,
    VideoQuality.P720: 720,
}


class PresetAvailabilityIssue(StrEnum):
    PLAYLIST_ITEM_REQUIRED = "playlist_item_required"
    VIDEO_QUALITY_UNAVAILABLE = "video_quality_unavailable"
    AUDIO_UNAVAILABLE = "audio_unavailable"


@dataclass(frozen=True, slots=True)
class PresetAvailability:
    requested_quality: VideoQuality | None
    available_video_qualities: tuple[VideoQuality, ...]
    issue: PresetAvailabilityIssue | None = None

    @property
    def available(self) -> bool:
        return self.issue is None


class PresetUnavailable(ValueError):
    """A typed, UI-safe explanation of why a preset cannot be queued."""

    def __init__(self, availability: PresetAvailability) -> None:
        issue = availability.issue
        if issue is None:
            raise ValueError("An available preset cannot produce PresetUnavailable")
        self.availability = availability
        self.requested_quality = availability.requested_quality
        self.available_video_qualities = availability.available_video_qualities
        reason = {
            PresetAvailabilityIssue.PLAYLIST_ITEM_REQUIRED: (
                "Select an individual playlist item before choosing a format"
            ),
            PresetAvailabilityIssue.VIDEO_QUALITY_UNAVAILABLE: (
                f"Requested video quality {availability.requested_quality.value} is unavailable"
                if availability.requested_quality is not None
                else "Requested video quality is unavailable"
            ),
            PresetAvailabilityIssue.AUDIO_UNAVAILABLE: (
                "The selected preset requires an audio-capable stream"
            ),
        }[issue]
        self.reason = reason
        super().__init__(reason)


def check_preset_availability(media: MediaInfo, preset: DownloadPreset) -> PresetAvailability:
    """Return availability without exposing provider format IDs or adapter details."""

    requested_quality = preset.quality if isinstance(preset, VideoPreset) else None
    qualities = _available_video_qualities(media)
    if media.playlist is not None:
        return PresetAvailability(
            requested_quality,
            qualities,
            PresetAvailabilityIssue.PLAYLIST_ITEM_REQUIRED,
        )

    has_audio = any(
        stream.kind in {StreamKind.AUDIO, StreamKind.AUDIO_VIDEO} for stream in media.streams
    )
    if not has_audio:
        return PresetAvailability(
            requested_quality,
            qualities,
            PresetAvailabilityIssue.AUDIO_UNAVAILABLE,
        )

    if isinstance(preset, VideoPreset):
        has_video = any(
            stream.kind in {StreamKind.VIDEO, StreamKind.AUDIO_VIDEO} for stream in media.streams
        )
        if not has_video or (
            preset.quality is not VideoQuality.BEST and preset.quality not in qualities
        ):
            return PresetAvailability(
                preset.quality,
                qualities,
                PresetAvailabilityIssue.VIDEO_QUALITY_UNAVAILABLE,
            )
    return PresetAvailability(requested_quality, qualities)


def require_preset_available(media: MediaInfo, preset: DownloadPreset) -> None:
    availability = check_preset_availability(media, preset)
    if not availability.available:
        raise PresetUnavailable(availability)


def _available_video_qualities(media: MediaInfo) -> tuple[VideoQuality, ...]:
    heights = {
        stream.height_pixels
        for stream in media.streams
        if stream.kind in {StreamKind.VIDEO, StreamKind.AUDIO_VIDEO}
    }
    return tuple(quality for quality, height in _QUALITY_HEIGHT.items() if height in heights)
