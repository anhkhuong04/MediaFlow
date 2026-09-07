"""Centralized user-facing text for the desktop presentation layer."""

from __future__ import annotations

from enum import StrEnum


class Language(StrEnum):
    ENGLISH = "en"
    VIETNAMESE = "vi"


class StringKey(StrEnum):
    """Stable keys that widgets use instead of scattering visible copy."""

    APP_NAME = "app.name"
    HOME = "navigation.home"
    DOWNLOADS = "navigation.downloads"
    HISTORY = "navigation.history"
    SETTINGS = "navigation.settings"
    HOME_PLACEHOLDER = "placeholder.home"
    DOWNLOADS_PLACEHOLDER = "placeholder.downloads"
    HISTORY_PLACEHOLDER = "placeholder.history"
    SETTINGS_PLACEHOLDER = "placeholder.settings"
    SHELL_STATUS_READY = "shell.status.ready"
    HOME_TITLE = "home.title"
    HOME_URL_LABEL = "home.url.label"
    HOME_URL_PLACEHOLDER = "home.url.placeholder"
    PASTE = "action.paste"
    CLEAR = "action.clear"
    ANALYZE = "action.analyze"
    CANCEL = "action.cancel"
    ADD_TO_DOWNLOADS = "action.add_to_downloads"
    VIDEO = "media.video"
    AUDIO = "media.audio"
    OUTPUT_LOCATION = "home.output_location"
    CHOOSE_FOLDER = "action.choose_folder"
    ADVANCED_OPTIONS = "home.advanced"
    ADVANCED_UNAVAILABLE = "home.advanced_unavailable"
    ANALYZING = "home.analyzing"
    ANALYZING_DELAYED = "home.analyzing_delayed"
    ANALYSIS_READY = "home.analysis_ready"
    CONVERSION_REQUIRED = "home.conversion_required"
    PRESET_LABEL = "home.preset"
    METADATA_UNAVAILABLE = "home.metadata_unavailable"
    PRESET_UNAVAILABLE = "home.preset_unavailable"
    URL_REQUIRED = "home.url_required"
    OUTPUT_REQUIRED = "home.output_required"
    NEW_URL_TITLE = "home.new_url_title"
    NEW_URL_BODY = "home.new_url_body"
    ANALYZE_NEW = "home.analyze_new"
    KEEP_CURRENT = "home.keep_current"
    QUEUED = "home.queued"
    ERROR_GENERIC_TITLE = "error.generic.title"
    ERROR_GENERIC_BODY = "error.generic.body"
    DOWNLOADS_TITLE = "downloads.title"
    ACTIVE = "downloads.active"
    QUEUED_SECTION = "downloads.queued"
    RECENTLY_COMPLETED = "downloads.recent"
    NO_ACTIVE = "downloads.empty_active"
    NO_QUEUED = "downloads.empty_queued"
    NO_RECENT = "downloads.empty_recent"
    OPEN_FILE = "action.open_file"
    OPEN_FOLDER = "action.open_folder"
    RETRY = "action.retry"
    RESUME = "action.resume"
    RESTART = "action.restart"
    RETRY_PROCESSING = "action.retry_processing"
    DETAILS = "action.details"
    CANCEL_DOWNLOAD_TITLE = "downloads.cancel_title"
    CANCEL_DOWNLOAD_BODY = "downloads.cancel_body"
    CANCEL_DOWNLOAD_CONFIRM = "downloads.cancel_confirm"
    STATUS_WAITING = "status.waiting"
    STATUS_DOWNLOADING = "status.downloading"
    STATUS_PROCESSING = "status.processing"
    STATUS_PAUSED = "status.paused"
    STATUS_INTERRUPTED = "status.interrupted"
    STATUS_COMPLETED = "status.completed"
    STATUS_FAILED = "status.failed"
    STATUS_CANCELLED = "status.cancelled"
    UNKNOWN_VALUE = "value.unknown"
    HISTORY_TITLE = "history.title"
    HISTORY_EMPTY = "history.empty"
    DOWNLOAD_AGAIN = "action.download_again"
    COPY_SOURCE_URL = "action.copy_source_url"
    REMOVE_HISTORY = "action.remove_history"
    DELETE_OUTPUT = "history.delete_output"
    REMOVE_HISTORY_TITLE = "history.remove_title"
    REMOVE_HISTORY_BODY = "history.remove_body"
    REMOVE_HISTORY_CONFIRM = "history.remove_confirm"
    OUTPUT_DELETE_RESULT = "history.output_delete_result"
    OUTPUT_UNAVAILABLE = "history.output_unavailable"


_ENGLISH: dict[StringKey, str] = {
    StringKey.APP_NAME: "MediaFlow",
    StringKey.HOME: "Home",
    StringKey.DOWNLOADS: "Downloads",
    StringKey.HISTORY: "History",
    StringKey.SETTINGS: "Settings",
    StringKey.HOME_PLACEHOLDER: "Paste and analyze a media URL here in the next milestone.",
    StringKey.DOWNLOADS_PLACEHOLDER: "Your active downloads will appear here.",
    StringKey.HISTORY_PLACEHOLDER: "Completed downloads will appear here.",
    StringKey.SETTINGS_PLACEHOLDER: "Application preferences will appear here.",
    StringKey.SHELL_STATUS_READY: "Application shell ready",
    StringKey.HOME_TITLE: "Download media",
    StringKey.HOME_URL_LABEL: "Media URL",
    StringKey.HOME_URL_PLACEHOLDER: "Paste a video, audio, or playlist URL",
    StringKey.PASTE: "Paste",
    StringKey.CLEAR: "Clear",
    StringKey.ANALYZE: "Analyze",
    StringKey.CANCEL: "Cancel",
    StringKey.ADD_TO_DOWNLOADS: "Add to downloads",
    StringKey.VIDEO: "Video",
    StringKey.AUDIO: "Audio",
    StringKey.OUTPUT_LOCATION: "Save to",
    StringKey.CHOOSE_FOLDER: "Choose folder",
    StringKey.ADVANCED_OPTIONS: "Advanced options",
    StringKey.ADVANCED_UNAVAILABLE: "No additional options are available for this preset yet.",
    StringKey.ANALYZING: "Analyzing the link…",
    StringKey.ANALYZING_DELAYED: "This is taking longer than usual. You can cancel safely.",
    StringKey.ANALYSIS_READY: "Choose a format and add it to downloads.",
    StringKey.CONVERSION_REQUIRED: "This option requires media conversion after download.",
    StringKey.PRESET_LABEL: "Format",
    StringKey.METADATA_UNAVAILABLE: "Some media details are unavailable.",
    StringKey.PRESET_UNAVAILABLE: "Unavailable for this media",
    StringKey.URL_REQUIRED: "Enter a media URL to continue.",
    StringKey.OUTPUT_REQUIRED: "Choose a folder for this download.",
    StringKey.NEW_URL_TITLE: "Analyze a new link?",
    StringKey.NEW_URL_BODY: "Your current download choices have not been added yet.",
    StringKey.ANALYZE_NEW: "Analyze new link",
    StringKey.KEEP_CURRENT: "Keep current choices",
    StringKey.QUEUED: "Added to Downloads.",
    StringKey.ERROR_GENERIC_TITLE: "We could not complete that action",
    StringKey.ERROR_GENERIC_BODY: "Check the link or try again.",
    StringKey.DOWNLOADS_TITLE: "Downloads",
    StringKey.ACTIVE: "Active",
    StringKey.QUEUED_SECTION: "Queued",
    StringKey.RECENTLY_COMPLETED: "Recently completed",
    StringKey.NO_ACTIVE: "No active downloads.",
    StringKey.NO_QUEUED: "Nothing is waiting in the queue.",
    StringKey.NO_RECENT: "Completed, failed, and cancelled downloads will appear here.",
    StringKey.OPEN_FILE: "Open file",
    StringKey.OPEN_FOLDER: "Open folder",
    StringKey.RETRY: "Retry download",
    StringKey.RESUME: "Resume",
    StringKey.RESTART: "Restart download",
    StringKey.RETRY_PROCESSING: "Retry processing",
    StringKey.DETAILS: "Details",
    StringKey.CANCEL_DOWNLOAD_TITLE: "Cancel this download?",
    StringKey.CANCEL_DOWNLOAD_BODY: "Partial download data is kept for recovery when available.",
    StringKey.CANCEL_DOWNLOAD_CONFIRM: "Cancel download",
    StringKey.STATUS_WAITING: "Waiting",
    StringKey.STATUS_DOWNLOADING: "Downloading",
    StringKey.STATUS_PROCESSING: "Processing",
    StringKey.STATUS_PAUSED: "Paused",
    StringKey.STATUS_INTERRUPTED: "Interrupted",
    StringKey.STATUS_COMPLETED: "Completed",
    StringKey.STATUS_FAILED: "Failed",
    StringKey.STATUS_CANCELLED: "Cancelled",
    StringKey.UNKNOWN_VALUE: "—",
    StringKey.HISTORY_TITLE: "History",
    StringKey.HISTORY_EMPTY: "No completed, failed, or cancelled downloads yet.",
    StringKey.DOWNLOAD_AGAIN: "Download again",
    StringKey.COPY_SOURCE_URL: "Copy source URL",
    StringKey.REMOVE_HISTORY: "Remove from history",
    StringKey.DELETE_OUTPUT: "Also delete the downloaded file",
    StringKey.REMOVE_HISTORY_TITLE: "Remove this history entry?",
    StringKey.REMOVE_HISTORY_BODY: "This removes the record from MediaFlow.",
    StringKey.REMOVE_HISTORY_CONFIRM: "Remove entry",
    StringKey.OUTPUT_DELETE_RESULT: "The downloaded file could not be removed.",
    StringKey.OUTPUT_UNAVAILABLE: "The downloaded file is no longer available.",
}

_VIETNAMESE: dict[StringKey, str] = {
    **_ENGLISH,
    StringKey.HOME: "Trang chủ",
    StringKey.DOWNLOADS: "Tải xuống",
    StringKey.HISTORY: "Lịch sử",
    StringKey.SETTINGS: "Cài đặt",
    StringKey.HOME_TITLE: "Tải nội dung",
    StringKey.PASTE: "Dán",
    StringKey.CLEAR: "Xóa",
    StringKey.ANALYZE: "Phân tích",
    StringKey.CANCEL: "Hủy",
    StringKey.ADD_TO_DOWNLOADS: "Thêm vào tải xuống",
    StringKey.OUTPUT_LOCATION: "Lưu vào",
    StringKey.CHOOSE_FOLDER: "Chọn thư mục",
    StringKey.QUEUED: "Đã thêm vào Tải xuống.",
    StringKey.HOME_PLACEHOLDER: (
        "Bạn sẽ dán và phân tích URL media ở đây trong milestone tiếp theo."
    ),
    StringKey.DOWNLOADS_PLACEHOLDER: "Các lượt tải đang hoạt động sẽ xuất hiện ở đây.",
    StringKey.HISTORY_PLACEHOLDER: "Các lượt tải đã hoàn tất sẽ xuất hiện ở đây.",
    StringKey.SETTINGS_PLACEHOLDER: "Tùy chọn ứng dụng sẽ xuất hiện ở đây.",
    StringKey.SHELL_STATUS_READY: "Khung ứng dụng đã sẵn sàng",
}

_TRANSLATIONS: dict[Language, dict[StringKey, str]] = {
    Language.ENGLISH: _ENGLISH,
    Language.VIETNAMESE: _VIETNAMESE,
}


class Localizer:
    """Resolve the current presentation language without coupling to Qt translation."""

    def __init__(self, language: Language = Language.ENGLISH) -> None:
        self._language = language

    @property
    def language(self) -> Language:
        return self._language

    def text(self, key: StringKey) -> str:
        return _TRANSLATIONS[self._language][key]
