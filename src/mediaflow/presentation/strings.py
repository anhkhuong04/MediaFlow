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
