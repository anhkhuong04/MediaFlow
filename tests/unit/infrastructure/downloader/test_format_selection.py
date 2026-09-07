import json
from dataclasses import replace
from pathlib import Path

import pytest

from mediaflow.domain import (
    AudioContainer,
    AudioPreset,
    MediaInfo,
    MediaStream,
    SourceUrl,
    StreamKind,
    VideoContainer,
    VideoPreset,
    VideoQuality,
)
from mediaflow.infrastructure.downloader import (
    PresetUnavailable,
    build_format_selection,
    select_format,
)
from mediaflow.infrastructure.downloader.yt_dlp_analyzer import normalize_metadata

FIXTURE = Path(__file__).parents[3] / "fixtures" / "yt_dlp" / "single_video.json"


def media() -> MediaInfo:
    with FIXTURE.open(encoding="utf-8") as fixture:
        raw: object = json.load(fixture)
    return normalize_metadata(raw, SourceUrl("https://example.com/watch/1"))


def test_selects_exact_video_quality_and_best_audio() -> None:
    selection = select_format(
        media(),
        VideoPreset(
            quality=VideoQuality.P1080,
            container=VideoContainer.MKV,
            preferred_frames_per_second=60,
        ),
    )

    assert selection.format_selector == (
        "bestvideo[height=1080][fps=60][has_drm!=?true]+bestaudio[has_drm!=?true]/"
        "best[height=1080][fps=60][vcodec!=none][acodec!=none][has_drm!=?true]/"
        "bestvideo[height=1080][has_drm!=?true]+bestaudio[has_drm!=?true]/"
        "best[height=1080][vcodec!=none][acodec!=none][has_drm!=?true]"
    )
    assert selection.output_container == "mkv"
    assert not selection.extract_audio


def test_best_video_uses_provider_independent_selector() -> None:
    selection = select_format(media(), VideoPreset(quality=VideoQuality.BEST))

    assert selection.format_selector == (
        "bestvideo[has_drm!=?true]+bestaudio[has_drm!=?true]/"
        "best[vcodec!=none][acodec!=none][has_drm!=?true]"
    )


def test_exact_combined_quality_has_no_lower_resolution_fallback() -> None:
    selection = select_format(media(), VideoPreset(quality=VideoQuality.P720))

    assert selection.format_selector == (
        "bestvideo[height=720][has_drm!=?true]+bestaudio[has_drm!=?true]/"
        "best[height=720][vcodec!=none][acodec!=none][has_drm!=?true]"
    )


@pytest.mark.parametrize(
    ("container", "expected_output"),
    [
        (AudioContainer.ORIGINAL, None),
        (AudioContainer.M4A, "m4a"),
        (AudioContainer.MP3, "mp3"),
    ],
)
def test_audio_preset_selects_best_audio(
    container: AudioContainer, expected_output: str | None
) -> None:
    selection = select_format(media(), AudioPreset(container=container))

    assert selection.format_selector == "bestaudio[has_drm!=?true]/best[has_drm!=?true]"
    assert selection.extract_audio
    assert selection.audio_output_format == expected_output


def test_exact_resolution_does_not_silently_fallback() -> None:
    with pytest.raises(PresetUnavailable) as raised:
        select_format(media(), VideoPreset(quality=VideoQuality.P2160))

    assert raised.value.requested_quality is VideoQuality.P2160
    assert raised.value.available_video_qualities == (
        VideoQuality.P1080,
        VideoQuality.P720,
    )


def test_download_request_can_rebuild_selector_without_provider_format_ids() -> None:
    selection = build_format_selection(VideoPreset(quality=VideoQuality.P1440))

    assert selection.format_selector == (
        "bestvideo[height=1440][has_drm!=?true]+bestaudio[has_drm!=?true]/"
        "best[height=1440][vcodec!=none][acodec!=none][has_drm!=?true]"
    )
    assert "v1080-60" not in selection.format_selector


@pytest.mark.parametrize(
    "preset",
    [VideoPreset(quality=VideoQuality.P1080), AudioPreset(container=AudioContainer.M4A)],
)
def test_selection_is_independent_of_stream_order(
    preset: VideoPreset | AudioPreset,
) -> None:
    original = media()
    reversed_media = replace(original, streams=tuple(reversed(original.streams)))

    assert select_format(original, preset) == select_format(reversed_media, preset)


def test_video_preset_rejects_media_without_audio() -> None:
    video_only = MediaInfo(
        source_url=SourceUrl("https://example.com/video-only"),
        title="Silent source",
        source_name="Example",
        streams=(
            MediaStream(
                key="video",
                kind=StreamKind.VIDEO,
                video_codec="vp9",
                height_pixels=1080,
            ),
        ),
    )

    with pytest.raises(PresetUnavailable, match="requires an audio-capable stream"):
        select_format(video_only, VideoPreset(quality=VideoQuality.P1080))
