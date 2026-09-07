"""Reusable shell widgets with no dependency on application or infrastructure code."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFrame, QLabel, QStyle, QToolButton, QVBoxLayout, QWidget

from mediaflow.presentation.design import TOKENS
from mediaflow.presentation.strings import Localizer, StringKey


class NavigationDestination(StrEnum):
    """The stable, top-level information architecture."""

    HOME = "home"
    DOWNLOADS = "downloads"
    HISTORY = "history"
    SETTINGS = "settings"


class PlaceholderPage(QWidget):
    """Temporary G1 content, deliberately replaceable by state-complete pages later."""

    def __init__(
        self,
        *,
        title_key: StringKey,
        description_key: StringKey,
        localizer: Localizer,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(f"{title_key.value.replace('.', '-')}-page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            TOKENS.spacing.large_section,
            TOKENS.spacing.large_section,
            TOKENS.spacing.large_section,
            TOKENS.spacing.large_section,
        )
        layout.setSpacing(TOKENS.spacing.section)

        title = QLabel(localizer.text(title_key), self)
        title.setObjectName("pageTitle")
        title.setWordWrap(True)
        layout.addWidget(title)

        card = QFrame(self)
        card.setObjectName("placeholderCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(
            TOKENS.spacing.section,
            TOKENS.spacing.section,
            TOKENS.spacing.section,
            TOKENS.spacing.section,
        )
        description = QLabel(localizer.text(description_key), card)
        description.setObjectName("placeholderText")
        description.setWordWrap(True)
        card_layout.addWidget(description)
        layout.addWidget(card)
        layout.addStretch(1)


def navigation_icon(destination: NavigationDestination, style: QStyle) -> QIcon:
    """Load the supplied navigation artwork, with a Qt icon as a safe package fallback."""

    asset_name = {
        NavigationDestination.HOME: "home.png",
        NavigationDestination.DOWNLOADS: "download.png",
        NavigationDestination.HISTORY: "history.png",
        NavigationDestination.SETTINGS: "setting.png",
    }[destination]
    icon = QIcon(str(_icon_path(asset_name)))
    if not icon.isNull():
        return icon

    standard_icon = {
        NavigationDestination.HOME: QStyle.StandardPixmap.SP_DirHomeIcon,
        NavigationDestination.DOWNLOADS: QStyle.StandardPixmap.SP_ArrowDown,
        NavigationDestination.HISTORY: QStyle.StandardPixmap.SP_FileDialogDetailedView,
        NavigationDestination.SETTINGS: QStyle.StandardPixmap.SP_FileDialogContentsView,
    }[destination]
    return style.standardIcon(standard_icon)


def brand_icon() -> QIcon:
    """Return the supplied blue MediaFlow mark for the shell header and footer."""

    return QIcon(str(_icon_path("logo.png")))


def footer_brand_icon() -> QIcon:
    """Return the supplied subdued MediaFlow mark used in the sidebar footer."""

    return QIcon(str(_icon_path("logo2.png")))


def _icon_path(name: str) -> Path:
    """Keep source and packaged assets beside the presentation code, never in user data."""

    return Path(__file__).with_name("icons") / name


def make_navigation_button(
    *,
    destination: NavigationDestination,
    label_key: StringKey,
    localizer: Localizer,
    style: QStyle,
    parent: QWidget,
) -> QToolButton:
    """Create an accessible navigation control for full and compact sidebars."""

    label = localizer.text(label_key)
    button = QToolButton(parent)
    button.setObjectName("navigationItem")
    button.setCheckable(True)
    button.setText(label)
    button.setIcon(navigation_icon(destination, style))
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    button.setAccessibleName(label)
    button.setAccessibleDescription(label)
    button.setToolTip(label)
    return button
