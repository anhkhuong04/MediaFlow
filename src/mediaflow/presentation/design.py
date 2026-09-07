"""Shared visual tokens and application-wide theme application."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication


class ThemeMode(StrEnum):
    """User preference for the presentation palette."""

    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


class ResolvedTheme(StrEnum):
    """A concrete palette selected for the current process."""

    LIGHT = "light"
    DARK = "dark"


class ShellWidth(StrEnum):
    """Responsive shell states; content screens refine their own layout later."""

    LARGE = "large"
    STANDARD = "standard"
    COMPACT = "compact"


@dataclass(frozen=True, slots=True)
class SpacingTokens:
    """The only spacing scale used by reusable presentation components."""

    micro: int = 4
    small: int = 8
    compact: int = 12
    standard: int = 16
    section: int = 24
    large_section: int = 32


@dataclass(frozen=True, slots=True)
class TypographyTokens:
    """System-font hierarchy expressed in point sizes."""

    page_title: int = 26
    section_title: int = 19
    body: int = 14
    secondary: int = 12


@dataclass(frozen=True, slots=True)
class RadiusTokens:
    """Moderate desktop radii, intentionally not mobile-pill values."""

    control: int = 8
    card: int = 12


@dataclass(frozen=True, slots=True)
class PaletteTokens:
    """Neutral surfaces and semantic colors for one resolved theme."""

    window: str
    surface: str
    surface_raised: str
    border: str
    text: str
    text_secondary: str
    disabled_text: str
    accent: str
    accent_text: str
    focus_ring: str
    success: str
    warning: str
    error: str


@dataclass(frozen=True, slots=True)
class DesignTokens:
    """Central source of visual measurements and palettes."""

    spacing: SpacingTokens = SpacingTokens()
    typography: TypographyTokens = TypographyTokens()
    radius: RadiusTokens = RadiusTokens()
    light: PaletteTokens = PaletteTokens(
        window="#f5f6f8",
        surface="#ffffff",
        surface_raised="#f9fafb",
        border="#d8dce3",
        text="#1d2430",
        text_secondary="#526071",
        disabled_text="#7a8492",
        accent="#0f6cbd",
        accent_text="#ffffff",
        focus_ring="#005fb8",
        success="#107c41",
        warning="#a15c00",
        error="#c42b1c",
    )
    dark: PaletteTokens = PaletteTokens(
        window="#1b1d21",
        surface="#22252b",
        surface_raised="#2a2e35",
        border="#424851",
        text="#f1f3f5",
        text_secondary="#c2c8d0",
        disabled_text="#89919d",
        accent="#4ca5ff",
        accent_text="#071b2f",
        focus_ring="#79b8ff",
        success="#61d095",
        warning="#f0ae63",
        error="#ff8b7d",
    )


TOKENS = DesignTokens()


def palette_for(theme: ResolvedTheme) -> PaletteTokens:
    """Resolve a concrete palette from the centralized design tokens."""

    return TOKENS.dark if theme is ResolvedTheme.DARK else TOKENS.light


class ThemeController(QObject):
    """Apply Light, Dark, or the Qt-reported system appearance without restart."""

    theme_changed = Signal(object)

    def __init__(self, application: QApplication, mode: ThemeMode = ThemeMode.SYSTEM) -> None:
        super().__init__(application)
        self._application = application
        self._mode = mode
        self._resolved_theme = self._resolve_theme()
        color_scheme_changed = getattr(application.styleHints(), "colorSchemeChanged", None)
        if color_scheme_changed is not None:
            color_scheme_changed.connect(self._handle_system_color_scheme)
        self._apply()

    @property
    def mode(self) -> ThemeMode:
        return self._mode

    @property
    def resolved_theme(self) -> ResolvedTheme:
        return self._resolved_theme

    def set_mode(self, mode: ThemeMode) -> None:
        """Apply a requested theme while retaining widget and navigation state."""

        if mode is self._mode:
            return
        self._mode = mode
        self._set_resolved_theme(self._resolve_theme())

    def apply_system_color_scheme(self, color_scheme: Qt.ColorScheme) -> None:
        """React to a platform appearance change; public for deterministic tests."""

        if self._mode is ThemeMode.SYSTEM:
            self._set_resolved_theme(_resolved_theme_for(color_scheme))

    def _handle_system_color_scheme(self, color_scheme: Qt.ColorScheme) -> None:
        self.apply_system_color_scheme(color_scheme)

    def _resolve_theme(self) -> ResolvedTheme:
        if self._mode is ThemeMode.LIGHT:
            return ResolvedTheme.LIGHT
        if self._mode is ThemeMode.DARK:
            return ResolvedTheme.DARK
        return _resolved_theme_for(self._application.styleHints().colorScheme())

    def _set_resolved_theme(self, theme: ResolvedTheme) -> None:
        if theme is self._resolved_theme:
            return
        self._resolved_theme = theme
        self._apply()
        self.theme_changed.emit(theme)

    def _apply(self) -> None:
        self._application.setStyleSheet(build_stylesheet(palette_for(self._resolved_theme)))


def _resolved_theme_for(color_scheme: Qt.ColorScheme) -> ResolvedTheme:
    return ResolvedTheme.DARK if color_scheme is Qt.ColorScheme.Dark else ResolvedTheme.LIGHT


def build_stylesheet(palette: PaletteTokens) -> str:
    """Build the compact application stylesheet exclusively from design tokens."""

    spacing = TOKENS.spacing
    radius = TOKENS.radius
    typography = TOKENS.typography
    return f"""
        QMainWindow#mediaflowWindow {{
            background: {palette.window};
            color: {palette.text};
        }}
        QWidget#shellRoot, QWidget#contentArea {{
            background: {palette.window};
        }}
        QFrame#sidebar {{
            background: {palette.surface};
            border-right: 1px solid {palette.border};
        }}
        QLabel#applicationName {{
            color: {palette.text};
            font-size: {typography.section_title}pt;
            font-weight: 600;
        }}
        QToolButton#navigationItem {{
            background: transparent;
            border: 1px solid transparent;
            border-radius: {radius.control}px;
            color: {palette.text};
            font-size: {typography.body}pt;
            padding: {spacing.compact}px;
            text-align: left;
        }}
        QToolButton#navigationItem:hover {{
            background: {palette.surface_raised};
        }}
        QToolButton#navigationItem:checked {{
            background: {palette.accent};
            color: {palette.accent_text};
            font-weight: 600;
        }}
        QToolButton#navigationItem:focus {{
            border: 2px solid {palette.focus_ring};
        }}
        QFrame#placeholderCard {{
            background: {palette.surface};
            border: 1px solid {palette.border};
            border-radius: {radius.card}px;
        }}
        QLabel#pageTitle {{
            color: {palette.text};
            font-size: {typography.page_title}pt;
            font-weight: 600;
        }}
        QLabel#placeholderText, QLabel#shellStatus {{
            color: {palette.text_secondary};
            font-size: {typography.body}pt;
        }}
        QLabel#shellStatus {{
            border-top: 1px solid {palette.border};
            padding-top: {spacing.standard}px;
        }}
        QLabel:disabled {{ color: {palette.disabled_text}; }}
        QScrollArea#screenScroll {{ border: none; background: transparent; }}
        QFrame#screenCard, QFrame#downloadCard {{
            background: {palette.surface};
            border: 1px solid {palette.border};
            border-radius: {radius.card}px;
        }}
        QLabel#secondaryText, QLabel#helperText {{ color: {palette.text_secondary}; }}
        QLabel#errorText {{ color: {palette.error}; }}
        QPushButton {{
            border: 1px solid {palette.border};
            border-radius: {radius.control}px;
            background: {palette.surface};
            color: {palette.text};
            padding: {spacing.small}px {spacing.compact}px;
        }}
        QPushButton:hover {{ background: {palette.surface_raised}; }}
        QPushButton#primaryAction {{
            background: {palette.accent}; color: {palette.accent_text};
            border-color: {palette.accent}; font-weight: 600;
        }}
        QLineEdit, QComboBox {{
            background: {palette.surface}; color: {palette.text};
            border: 1px solid {palette.border}; border-radius: {radius.control}px;
            padding: {spacing.small}px;
        }}
        QLineEdit:focus, QComboBox:focus, QPushButton:focus, QToolButton:focus {{
            border: 2px solid {palette.focus_ring};
        }}
    """
