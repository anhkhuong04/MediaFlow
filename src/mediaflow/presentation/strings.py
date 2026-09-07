"""Centralized user-facing text for the desktop presentation layer."""

from __future__ import annotations

from enum import StrEnum


class Language(StrEnum):
    """Languages prepared for the first desktop release."""

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


_TRANSLATIONS: dict[Language, dict[StringKey, str]] = {
    Language.ENGLISH: {
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
    },
    Language.VIETNAMESE: {
        StringKey.APP_NAME: "MediaFlow",
        StringKey.HOME: "Trang chủ",
        StringKey.DOWNLOADS: "Tải xuống",
        StringKey.HISTORY: "Lịch sử",
        StringKey.SETTINGS: "Cài đặt",
        StringKey.HOME_PLACEHOLDER: (
            "Bạn sẽ dán và phân tích URL media ở đây trong milestone tiếp theo."
        ),
        StringKey.DOWNLOADS_PLACEHOLDER: "Các lượt tải đang hoạt động sẽ xuất hiện ở đây.",
        StringKey.HISTORY_PLACEHOLDER: "Các lượt tải đã hoàn tất sẽ xuất hiện ở đây.",
        StringKey.SETTINGS_PLACEHOLDER: "Tùy chọn ứng dụng sẽ xuất hiện ở đây.",
        StringKey.SHELL_STATUS_READY: "Khung ứng dụng đã sẵn sàng",
    },
}


class Localizer:
    """Resolve the current presentation language without coupling to Qt translation."""

    def __init__(self, language: Language = Language.ENGLISH) -> None:
        self._language = language

    @property
    def language(self) -> Language:
        return self._language

    def text(self, key: StringKey) -> str:
        """Return translated copy for a stable presentation key."""

        return _TRANSLATIONS[self._language][key]
