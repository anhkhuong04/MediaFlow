from collections.abc import Mapping
from dataclasses import dataclass, field

import pytest
from yt_dlp.utils import DownloadCancelled, DownloadError  # type: ignore[import-untyped]

from mediaflow.domain import FailureCategory, SourceUrl
from mediaflow.infrastructure.downloader import (
    AnalysisDiagnostic,
    YtDlpAnalyzer,
    YtDlpAnalyzerOptions,
    map_ytdlp_error,
)


@dataclass(slots=True)
class Token:
    values: list[bool]

    def is_cancelled(self) -> bool:
        if len(self.values) > 1:
            return self.values.pop(0)
        return self.values[0]


@dataclass(slots=True)
class Session:
    result: object = field(
        default_factory=lambda: {
            "title": "Title",
            "extractor": "Example",
            "formats": [{"format_id": "a1", "vcodec": "none", "acodec": "opus"}],
        }
    )
    error: Exception | None = None
    parameters: Mapping[str, object] | None = None

    def __enter__(self) -> "Session":
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object | None,
    ) -> bool | None:
        return None

    def extract_info(self, url: str, *, download: bool) -> object:
        assert url == "https://example.com/watch/1"
        assert not download
        if self.parameters is not None:
            callback = self.parameters["match_filter"]
            assert callable(callback)
            callback({}, incomplete=False)
        if self.error is not None:
            raise self.error
        return self.result


@dataclass(slots=True)
class Factory:
    session: Session
    calls: list[Mapping[str, object]] = field(default_factory=list)

    def __call__(self, parameters: Mapping[str, object]) -> Session:
        self.calls.append(parameters)
        self.session.parameters = parameters
        return self.session


@dataclass(slots=True)
class Diagnostics:
    values: list[AnalysisDiagnostic] = field(default_factory=list)

    def report(self, diagnostic: AnalysisDiagnostic) -> None:
        self.values.append(diagnostic)


def test_adapter_uses_safe_minimal_options_and_preserves_requested_url() -> None:
    factory = Factory(Session())
    analyzer = YtDlpAnalyzer(
        options=YtDlpAnalyzerOptions(socket_timeout_seconds=7.5), client_factory=factory
    )
    requested = SourceUrl("https://example.com/watch/1")

    outcome = analyzer.analyze(requested, cancellation=Token([False]))

    assert outcome.media is not None
    assert outcome.media.source_url == requested
    parameters = factory.calls[0]
    assert parameters["socket_timeout"] == 7.5
    assert parameters["skip_download"] is True
    assert parameters["quiet"] is True
    assert parameters["no_warnings"] is True
    assert parameters["cachedir"] is False
    assert "cookiefile" not in parameters
    assert "cookiesfrombrowser" not in parameters
    logger = parameters["logger"]
    assert hasattr(logger, "error")


def test_cancelled_before_engine_does_not_create_session() -> None:
    factory = Factory(Session())

    outcome = YtDlpAnalyzer(client_factory=factory).analyze(
        SourceUrl("https://example.com/watch/1"), cancellation=Token([True])
    )

    assert outcome.failure is not None
    assert outcome.failure.category is FailureCategory.CANCELLED
    assert factory.calls == []


def test_match_filter_provides_cooperative_cancellation() -> None:
    diagnostics = Diagnostics()
    outcome = YtDlpAnalyzer(client_factory=Factory(Session()), diagnostics=diagnostics).analyze(
        SourceUrl("https://example.com/watch/1"), cancellation=Token([False, True])
    )

    assert outcome.failure is not None
    assert outcome.failure.category is FailureCategory.CANCELLED
    assert isinstance(diagnostics.values[0].__cause__, DownloadCancelled)


def test_failure_is_sanitized_while_diagnostic_retains_cause() -> None:
    raw = DownloadError("HTTP Error 403 token=super-secret")
    diagnostics = Diagnostics()
    outcome = YtDlpAnalyzer(
        client_factory=Factory(Session(error=raw)), diagnostics=diagnostics
    ).analyze(SourceUrl("https://example.com/watch/1"), cancellation=Token([False]))

    assert outcome.failure is not None
    assert outcome.failure.category is FailureCategory.ACCESS_DENIED
    diagnostic = diagnostics.values[0]
    assert diagnostic.__cause__ is raw
    assert str(diagnostic) == "analysis.access_denied"
    assert "super-secret" not in str(diagnostic)


@pytest.mark.parametrize(
    ("message", "category", "code", "retryable"),
    [
        (
            "Unsupported URL",
            FailureCategory.UNSUPPORTED_SOURCE,
            "analysis.unsupported_source",
            False,
        ),
        ("Please sign in", FailureCategory.AUTH_REQUIRED, "analysis.auth_required", False),
        (
            "HTTP Error 401: Unauthorized",
            FailureCategory.AUTH_REQUIRED,
            "analysis.auth_required",
            False,
        ),
        (
            "This is a private video",
            FailureCategory.AUTH_REQUIRED,
            "analysis.auth_required",
            False,
        ),
        (
            "HTTP Error 403: Forbidden",
            FailureCategory.ACCESS_DENIED,
            "analysis.access_denied",
            False,
        ),
        (
            "This video is not available in your country",
            FailureCategory.ACCESS_DENIED,
            "analysis.access_denied",
            False,
        ),
        (
            "Video unavailable",
            FailureCategory.MEDIA_UNAVAILABLE,
            "analysis.media_unavailable",
            False,
        ),
        (
            "This media has been removed",
            FailureCategory.MEDIA_UNAVAILABLE,
            "analysis.media_unavailable",
            False,
        ),
        ("Connection timed out", FailureCategory.NETWORK, "analysis.network", True),
        ("Extractor changed", FailureCategory.UNEXPECTED, "analysis.engine_error", False),
    ],
)
def test_error_mapping_is_specific_when_evidence_is_available(
    message: str, category: FailureCategory, code: str, retryable: bool
) -> None:
    failure = map_ytdlp_error(DownloadError(message))

    assert failure.category is category
    assert failure.code == code
    assert failure.retryable is retryable


def test_timeout_must_be_positive() -> None:
    with pytest.raises(ValueError):
        YtDlpAnalyzerOptions(socket_timeout_seconds=0)
