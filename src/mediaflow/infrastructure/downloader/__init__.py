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
from mediaflow.infrastructure.downloader.yt_dlp_downloader import (
    DownloadDiagnostic,
    DownloadDiagnosticSink,
    YtDlpDownloader,
    YtDlpDownloaderOptions,
    map_ytdlp_download_error,
    normalize_download_progress,
)

__all__ = [
    "AnalysisDiagnostic",
    "AnalysisDiagnosticSink",
    "DownloadDiagnostic",
    "DownloadDiagnosticSink",
    "PresetUnavailable",
    "YtDlpAnalyzer",
    "YtDlpAnalyzerOptions",
    "YtDlpDownloader",
    "YtDlpDownloaderOptions",
    "YtDlpFormatSelection",
    "build_format_selection",
    "map_ytdlp_error",
    "map_ytdlp_download_error",
    "normalize_download_progress",
    "normalize_metadata",
    "select_format",
]
