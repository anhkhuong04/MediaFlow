"""Windows-safe output names, conflict handling, and atomic publication."""

import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from mediaflow.application import ConflictPolicy
from mediaflow.domain import OutputPath

_INVALID_WINDOWS_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class OutputPathError(ValueError):
    pass


class OutputConflictError(FileExistsError):
    pass


@dataclass(frozen=True, slots=True)
class WindowsPathPolicy:
    maximum_path_characters: int = 240
    maximum_filename_characters: int = 180

    def __post_init__(self) -> None:
        if self.maximum_path_characters < 32 or self.maximum_filename_characters < 8:
            raise ValueError("Windows path limits are too small")


_DEFAULT_PATH_POLICY = WindowsPathPolicy()


def sanitize_windows_filename(value: str) -> str:
    """Return a non-empty Windows-safe filename stem."""

    normalized = unicodedata.normalize("NFC", value)
    sanitized = _INVALID_WINDOWS_CHARACTERS.sub("_", normalized).strip().rstrip(". ")
    if not sanitized:
        sanitized = "media"
    if sanitized.split(".", 1)[0].upper() in _RESERVED_NAMES:
        sanitized = f"_{sanitized}"
    return sanitized


def select_output_path(
    directory: OutputPath,
    *,
    title: str,
    extension: str,
    conflict_policy: ConflictPolicy,
    path_policy: WindowsPathPolicy = _DEFAULT_PATH_POLICY,
) -> OutputPath:
    """Select a deterministic candidate without modifying the filesystem."""

    suffix = _normalized_extension(extension)
    stem = sanitize_windows_filename(title)
    desired = _candidate(directory.value, stem, suffix, None, path_policy)
    if not desired.exists() or conflict_policy is ConflictPolicy.REPLACE:
        return OutputPath(desired)
    if conflict_policy is ConflictPolicy.SKIP:
        raise OutputConflictError("Output already exists and conflict policy is skip")
    for index in range(1, 10_000):
        candidate = _candidate(directory.value, stem, suffix, index, path_policy)
        if not candidate.exists():
            return OutputPath(candidate)
    raise OutputConflictError("No available renamed output path")


def temporary_output_path(final_path: OutputPath) -> OutputPath:
    """Create a unique sibling name while preserving the media extension."""

    path = final_path.value
    temporary_name = f".mediaflow-{uuid4().hex}{path.suffix}"
    return OutputPath(path.with_name(temporary_name))


def publish_atomic(
    temporary_path: OutputPath,
    final_path: OutputPath,
    *,
    conflict_policy: ConflictPolicy,
) -> None:
    """Publish a sibling temporary file without implicit replacement."""

    source = temporary_path.value
    destination = final_path.value
    if source.parent.resolve(strict=False) != destination.parent.resolve(strict=False):
        raise OutputPathError("Atomic publication requires sibling paths")
    if conflict_policy is ConflictPolicy.REPLACE:
        os.replace(source, destination)
        return
    try:
        os.link(source, destination)
    except FileExistsError as error:
        raise OutputConflictError("Output appeared before atomic publication") from error
    source.unlink()


def _candidate(
    directory: Path,
    stem: str,
    suffix: str,
    index: int | None,
    policy: WindowsPathPolicy,
) -> Path:
    decoration = "" if index is None else f" ({index})"
    maximum_stem = min(
        policy.maximum_filename_characters - len(suffix) - len(decoration),
        policy.maximum_path_characters - len(str(directory)) - 1 - len(suffix) - len(decoration),
    )
    if maximum_stem < 1:
        raise OutputPathError("Output directory leaves no room for a filename")
    trimmed = stem[:maximum_stem].rstrip(". ") or "m"
    path = directory / f"{trimmed}{decoration}{suffix}"
    if len(path.name) > policy.maximum_filename_characters or len(str(path)) > (
        policy.maximum_path_characters
    ):
        raise OutputPathError("Output path exceeds the configured Windows limit")
    return path


def _normalized_extension(extension: str) -> str:
    value = extension.casefold().strip().lstrip(".")
    if not value or not value.isalnum():
        raise OutputPathError("Output extension must be alphanumeric")
    return f".{value}"
