"""Opt-in live analyzer/downloader check for explicitly authorized media.

Run with ``MEDIAFLOW_SMOKE_URL`` set and pytest socket access explicitly enabled.
The URL is deliberately supplied at runtime and never becomes a suite dependency.
"""

import os
from pathlib import Path

import pytest

from mediaflow.application import DownloadJob
from mediaflow.domain import (
    AttemptId,
    DownloadRequest,
    OutputPath,
    SourceUrl,
    TaskId,
    VideoPreset,
)
from mediaflow.infrastructure.downloader import YtDlpAnalyzer, YtDlpDownloader


class _ActiveToken:
    def is_cancelled(self) -> bool:
        return False


class _DiscardProgress:
    def report(self, progress: object) -> None:
        del progress


@pytest.mark.smoke
def test_live_url_can_be_analyzed_and_downloaded(tmp_path: Path) -> None:
    raw_url = os.environ.get("MEDIAFLOW_SMOKE_URL")
    if raw_url is None:
        pytest.skip("MEDIAFLOW_SMOKE_URL is not configured")

    outcome = YtDlpAnalyzer().analyze(SourceUrl(raw_url), cancellation=_ActiveToken())

    assert outcome.media is not None, outcome.failure
    assert outcome.media.streams or outcome.media.playlist is not None
    assert outcome.media.playlist is None, "C9 smoke URL must resolve to one media item"

    download = YtDlpDownloader().download(
        DownloadJob(
            TaskId.new(),
            AttemptId.new(),
            DownloadRequest(
                outcome.media.source_url,
                outcome.media.title,
                VideoPreset(),
                OutputPath(tmp_path.resolve()),
            ),
        ),
        progress=_DiscardProgress(),
        cancellation=_ActiveToken(),
    )

    assert download.artifact is not None, download.failure
    assert all(
        path.value.is_file() and path.value.stat().st_size > 0 for path in download.artifact.paths
    )
