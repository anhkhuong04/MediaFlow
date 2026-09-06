"""Map user presets to stable yt-dlp format selectors."""

from dataclasses import dataclass

from mediaflow.application import require_preset_available
from mediaflow.domain import (
    AudioContainer,
    AudioPreset,
    DownloadPreset,
    MediaInfo,
    VideoQuality,
)

_QUALITY_HEIGHT = {
    VideoQuality.P2160: 2160,
    VideoQuality.P1440: 1440,
    VideoQuality.P1080: 1080,
    VideoQuality.P720: 720,
}


@dataclass(frozen=True, slots=True)
class YtDlpFormatSelection:
    """Infrastructure-only execution plan containing no provider format IDs."""

    format_selector: str
    output_container: str | None
    extract_audio: bool
    audio_output_format: str | None = None


def select_format(media: MediaInfo, preset: DownloadPreset) -> YtDlpFormatSelection:
    """Validate through the application contract, then build a stable selector."""

    require_preset_available(media, preset)
    return build_format_selection(preset)


def build_format_selection(preset: DownloadPreset) -> YtDlpFormatSelection:
    """Build the execution plan that C5 can reproduce from ``DownloadRequest``."""

    if isinstance(preset, AudioPreset):
        output_format = (
            None if preset.container is AudioContainer.ORIGINAL else preset.container.value
        )
        return YtDlpFormatSelection(
            format_selector="bestaudio[has_drm!=True]/best[has_drm!=True]",
            output_container=None,
            extract_audio=True,
            audio_output_format=output_format,
        )

    quality_filter = ""
    if preset.quality is not VideoQuality.BEST:
        quality_filter = f"[height={_QUALITY_HEIGHT[preset.quality]}]"
    playable_filter = "[has_drm!=True]"
    combined_filter = f"{quality_filter}[vcodec!=none][acodec!=none]{playable_filter}"
    base_selector = (
        f"bestvideo{quality_filter}{playable_filter}+bestaudio{playable_filter}/"
        f"best{combined_filter}"
    )
    selector = base_selector
    if preset.preferred_frames_per_second is not None:
        fps_filter = f"[fps={preset.preferred_frames_per_second}]"
        preferred = (
            f"bestvideo{quality_filter}{fps_filter}{playable_filter}+"
            f"bestaudio{playable_filter}/"
            f"best{quality_filter}{fps_filter}[vcodec!=none][acodec!=none]"
            f"{playable_filter}"
        )
        selector = f"{preferred}/{base_selector}"
    return YtDlpFormatSelection(
        format_selector=selector,
        output_container=preset.container.value,
        extract_audio=False,
    )
