"""yt-dlp adapters and format selection."""

from mediaflow.application import PresetUnavailable
from mediaflow.infrastructure.downloader.format_selection import (
    YtDlpFormatSelection,
    build_format_selection,
    select_format,
)
from mediaflow.infrastructure.downloader.yt_dlp_analyzer import (
    AnalysisDiagnostic,
    AnalysisDiagnosticSink,
    YtDlpAnalyzer,
    YtDlpAnalyzerOptions,
    map_ytdlp_error,
    normalize_metadata,
)

__all__ = [
    "AnalysisDiagnostic",
    "AnalysisDiagnosticSink",
    "PresetUnavailable",
    "YtDlpAnalyzer",
    "YtDlpAnalyzerOptions",
    "YtDlpFormatSelection",
    "build_format_selection",
    "map_ytdlp_error",
    "normalize_metadata",
    "select_format",
]
