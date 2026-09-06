from datetime import UTC, datetime
from pathlib import Path

import pytest

from mediaflow.application import (
    EnqueueDownload,
    PresetAvailabilityIssue,
    PresetUnavailable,
    check_preset_availability,
)
from mediaflow.domain import (
    MediaInfo,
    MediaStream,
    OutputPath,
    PlaylistSummary,
    SourceUrl,
    StreamKind,
    UtcTimestamp,
    VideoPreset,
    VideoQuality,
)
from tests.unit.application.fakes import (
    CollectingEventPublisher,
    FakeClock,
    InMemoryTaskRepository,
)

NOW = UtcTimestamp(datetime(2026, 9, 7, tzinfo=UTC))


def media(*streams: MediaStream, playlist: PlaylistSummary | None = None) -> MediaInfo:
    return MediaInfo(
        source_url=SourceUrl("https://example.com/media"),
        title="Media",
        source_name="Example",
        streams=streams,
        playlist=playlist,
    )


def test_availability_exposes_supported_choices_without_provider_ids() -> None:
    analyzed = media(
        MediaStream(key="provider-video", kind=StreamKind.VIDEO, height_pixels=1080),
        MediaStream(key="provider-audio", kind=StreamKind.AUDIO),
    )

    availability = check_preset_availability(analyzed, VideoPreset(quality=VideoQuality.P2160))

    assert not availability.available
    assert availability.issue is PresetAvailabilityIssue.VIDEO_QUALITY_UNAVAILABLE
    assert availability.available_video_qualities == (VideoQuality.P1080,)


@pytest.mark.parametrize(
    ("analyzed", "issue"),
    [
        (
            media(playlist=PlaylistSummary(item_count=2, available_item_count=2)),
            PresetAvailabilityIssue.PLAYLIST_ITEM_REQUIRED,
        ),
        (
            media(MediaStream(key="video", kind=StreamKind.VIDEO, height_pixels=1080)),
            PresetAvailabilityIssue.AUDIO_UNAVAILABLE,
        ),
    ],
)
def test_enqueue_rejects_unavailable_preset_before_persistence(
    analyzed: MediaInfo, issue: PresetAvailabilityIssue, tmp_path: Path
) -> None:
    repository = InMemoryTaskRepository()
    events = CollectingEventPublisher()
    clock = FakeClock([NOW])

    with pytest.raises(PresetUnavailable) as raised:
        EnqueueDownload(repository, events, clock).execute(
            media=analyzed,
            preset=VideoPreset(quality=VideoQuality.P1080),
            output_directory=OutputPath(tmp_path),
        )

    assert raised.value.availability.issue is issue
    assert repository.list_downloads() == ()
    assert events.events == []
    assert clock.values == [NOW]
