"""Opt-in live analyzer check.

Run with ``MEDIAFLOW_SMOKE_URL`` set and pytest socket access explicitly enabled.
"""

import os

import pytest

from mediaflow.domain import SourceUrl
from mediaflow.infrastructure.downloader import YtDlpAnalyzer


class _ActiveToken:
    def is_cancelled(self) -> bool:
        return False


@pytest.mark.smoke
def test_live_url_can_be_normalized() -> None:
    raw_url = os.environ.get("MEDIAFLOW_SMOKE_URL")
    if raw_url is None:
        pytest.skip("MEDIAFLOW_SMOKE_URL is not configured")

    outcome = YtDlpAnalyzer().analyze(SourceUrl(raw_url), cancellation=_ActiveToken())

    assert outcome.media is not None, outcome.failure
    assert outcome.media.streams or outcome.media.playlist is not None
