from pathlib import Path

import pytest

from mediaflow.application import SuggestedAction, message_for_failure
from mediaflow.domain import Failure, FailureCategory, SourceUrl
from mediaflow.infrastructure.downloader.yt_dlp_analyzer import AnalysisDiagnostic
from mediaflow.infrastructure.downloader.yt_dlp_downloader import DownloadDiagnostic


@pytest.mark.parametrize(
    ("failure", "expected_action"),
    [
        (Failure(FailureCategory.NETWORK, "download.network", True), SuggestedAction.RETRY),
        (
            Failure(FailureCategory.PROCESSING, "processing.ffmpeg_failed", True),
            SuggestedAction.RETRY_PROCESSING,
        ),
        (
            Failure(FailureCategory.DISK_SPACE, "processing.disk_space", True),
            SuggestedAction.CHOOSE_FOLDER,
        ),
        (
            Failure(FailureCategory.DEPENDENCY, "processing.ffmpeg_missing", False),
            SuggestedAction.CONFIGURE_DEPENDENCY,
        ),
        (
            Failure(FailureCategory.MEDIA_UNAVAILABLE, "analysis.media_unavailable", False),
            SuggestedAction.VIEW_DETAILS,
        ),
    ],
)
def test_failure_lanes_expose_stable_codes_and_truthful_retry_actions(
    failure: Failure, expected_action: SuggestedAction
) -> None:
    message = message_for_failure(failure)

    assert message.technical_code == failure.code
    assert message.suggested_action is expected_action
    assert "http" not in repr(message).casefold()


@pytest.mark.parametrize("diagnostic_type", [AnalysisDiagnostic, DownloadDiagnostic])
def test_adapter_diagnostic_envelope_does_not_render_raw_secret_or_path(
    diagnostic_type: type[AnalysisDiagnostic] | type[DownloadDiagnostic],
) -> None:
    secret = "private-cookie-token"
    sensitive_path = Path(r"C:\Users\Private Person\Downloads\private.mp4")
    diagnostic = diagnostic_type(Failure(FailureCategory.UNEXPECTED, "engine.unexpected", False))
    diagnostic.__cause__ = RuntimeError(f"cookie={secret}; output={sensitive_path}")

    rendered = f"{diagnostic!s} {diagnostic!r}"
    assert rendered == f"engine.unexpected {diagnostic_type.__name__}('engine.unexpected')"
    assert secret not in rendered
    assert str(sensitive_path) not in rendered


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/video?token=private",
        "https://example.com/video?X-Amz-Signature=private",
        "https://user:password@example.com/video",
        "https://example.com/video#id_token=private",
    ],
)
def test_credential_bearing_urls_are_rejected_before_public_diagnostics(url: str) -> None:
    with pytest.raises(ValueError):
        SourceUrl(url)
