from dataclasses import FrozenInstanceError

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


def video_stream() -> MediaStream:
    return MediaStream(
        key="normalized-stream-1",
        kind=StreamKind.VIDEO,
        container="mp4",
        video_codec="avc1",
        width_pixels=1920,
        height_pixels=1080,
        frames_per_second=60,
        bitrate_kilobits_per_second=4500,
        size_bytes=10_000_000,
    )


def test_media_info_and_presets_are_immutable_normalized_models() -> None:
    source = SourceUrl("https://example.com/watch?v=abc")
    info = MediaInfo(
        source_url=source,
        title="Example video",
        source_name="Example",
        streams=(video_stream(),),
        duration_seconds=42.5,
    )
    preset = VideoPreset(
        quality=VideoQuality.P1080,
        container=VideoContainer.MP4,
        preferred_frames_per_second=60,
    )
    assert info.streams[0].height_pixels == 1080
    assert preset.quality is VideoQuality.P1080
    assert AudioPreset(container=AudioContainer.MP3).container is AudioContainer.MP3
    with pytest.raises(FrozenInstanceError):
        setattr(info, "title", "Changed")  # noqa: B010 - exercise frozen runtime behavior


@pytest.mark.parametrize(
    "stream",
    [
        MediaStream(key="valid", kind=StreamKind.AUDIO),
        MediaStream(key="valid", kind=StreamKind.AUDIO_VIDEO, size_bytes=1),
    ],
)
def test_stream_allows_partial_metadata(stream: MediaStream) -> None:
    assert stream.key == "valid"


def test_stream_rejects_invalid_units_and_untrimmed_values() -> None:
    with pytest.raises(ValueError):
        MediaStream(key=" ", kind=StreamKind.VIDEO)
    with pytest.raises(ValueError):
        MediaStream(key="valid", kind=StreamKind.VIDEO, height_pixels=0)
    with pytest.raises(ValueError):
        MediaStream(key="valid", kind=StreamKind.VIDEO, audio_codec=" aac")


def test_media_info_requires_display_identity_and_a_stream() -> None:
    source = SourceUrl("https://example.com/media")
    with pytest.raises(ValueError):
        MediaInfo(source_url=source, title="", source_name="Example", streams=(video_stream(),))
    with pytest.raises(ValueError):
        MediaInfo(source_url=source, title="Title", source_name="Example", streams=())
    with pytest.raises(ValueError):
        MediaInfo(
            source_url=source,
            title="Title",
            source_name="Example",
            streams=(video_stream(),),
            duration_seconds=-1,
        )
