import json
from pathlib import Path

import pytest

from mediaflow.domain import SourceUrl, StreamKind
from mediaflow.infrastructure.downloader.yt_dlp_analyzer import (
    MetadataNormalizationError,
    normalize_metadata,
)

FIXTURES = Path(__file__).parents[3] / "fixtures" / "yt_dlp"


def load_fixture(name: str) -> object:
    with (FIXTURES / name).open(encoding="utf-8") as fixture:
        return json.load(fixture)


def test_normalizes_single_media_without_leaking_raw_dictionary() -> None:
    requested = SourceUrl("https://example.com/watch?v=user-input")

    media = normalize_metadata(load_fixture("single_video.json"), requested)

    assert media.source_url == requested
    assert media.canonical_url == SourceUrl("https://example.com/canonical/example-1")
    assert media.title == "Example video"
    assert media.source_name == "Example"
    assert media.uploader == "Example channel"
    assert media.duration_seconds == 125.5
    assert media.thumbnail_url == SourceUrl("https://cdn.example.com/example-1.jpg")
    assert media.has_subtitles
    assert media.has_automatic_captions
    assert media.chapter_count == 2
    assert media.playlist is None
    assert [stream.kind for stream in media.streams] == [
        StreamKind.VIDEO,
        StreamKind.VIDEO,
        StreamKind.AUDIO_VIDEO,
        StreamKind.AUDIO,
    ]
    assert media.streams[0].size_bytes == 51_000_000


def test_playlist_summary_has_no_fake_streams() -> None:
    requested = SourceUrl("https://example.com/list?id=1")

    media = normalize_metadata(load_fixture("playlist.json"), requested)

    assert media.source_url == requested
    assert media.streams == ()
    assert media.playlist is not None
    assert media.playlist.item_count == 4
    assert media.playlist.available_item_count == 2


def test_wrong_types_and_unknown_optional_values_do_not_crash() -> None:
    raw: object = {
        "title": 12,
        "extractor": " Example ",
        "duration": "unknown",
        "thumbnail": "not a URL",
        "is_live": "yes",
        "subtitles": [],
        "chapters": "invalid",
        "formats": [
            {
                "format_id": "audio",
                "vcodec": "none",
                "acodec": "opus",
                "filesize": False,
                "abr": "unknown",
            },
            None,
        ],
    }

    media = normalize_metadata(raw, SourceUrl("https://example.com/media"))

    assert media.title == "Untitled media"
    assert media.source_name == "Example"
    assert media.duration_seconds is None
    assert media.thumbnail_url is None
    assert not media.is_live
    assert not media.has_subtitles
    assert media.chapter_count == 0
    assert media.streams[0].size_bytes is None
    assert media.streams[0].bitrate_kilobits_per_second is None


def test_credential_bearing_canonical_url_is_not_exposed() -> None:
    raw: object = {
        "title": "Title",
        "extractor": "Example",
        "webpage_url": "https://cdn.example.com/media?token=secret",
        "formats": [{"format_id": "audio", "vcodec": "none", "acodec": "opus"}],
    }
    requested = SourceUrl("https://example.com/watch/1")

    media = normalize_metadata(raw, requested)

    assert media.source_url == requested
    assert media.canonical_url is None


@pytest.mark.parametrize("invalid_number", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_numeric_metadata_is_treated_as_unknown(invalid_number: float) -> None:
    raw: object = {
        "title": "Title",
        "extractor": "Example",
        "duration": invalid_number,
        "formats": [
            {
                "format_id": "video",
                "vcodec": "vp9",
                "acodec": "none",
                "fps": invalid_number,
                "vbr": invalid_number,
            }
        ],
    }

    media = normalize_metadata(raw, SourceUrl("https://example.com/watch/1"))

    assert media.duration_seconds is None
    assert media.streams[0].frames_per_second is None
    assert media.streams[0].bitrate_kilobits_per_second is None


@pytest.mark.parametrize("raw", [None, [], {}, {"formats": [None, {"vcodec": "none"}]}])
def test_rejects_metadata_without_media_or_playlist(raw: object) -> None:
    with pytest.raises(MetadataNormalizationError):
        normalize_metadata(raw, SourceUrl("https://example.com/media"))
