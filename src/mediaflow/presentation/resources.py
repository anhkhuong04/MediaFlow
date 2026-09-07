"""Resource lookup that works from source and a future bundled Windows build."""

from __future__ import annotations

import sys
from pathlib import Path, PurePath


def resource_directory() -> Path:
    """Return the package resource root without relying on a local absolute path."""

    bundle_root = getattr(sys, "_MEIPASS", None)
    if isinstance(bundle_root, str):
        return Path(bundle_root) / "mediaflow" / "resources"
    return Path(__file__).with_name("resources")


def resource_path(relative_name: str) -> Path:
    """Resolve a bundled resource name while rejecting parent-directory traversal."""

    relative_path = PurePath(relative_name)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("Resource paths must remain inside the package resource directory")
    return resource_directory() / relative_path
