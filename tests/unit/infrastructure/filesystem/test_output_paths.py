from pathlib import Path

import pytest

from mediaflow.application import ConflictPolicy
from mediaflow.domain import OutputPath
from mediaflow.infrastructure.filesystem import (
    OutputConflictError,
    OutputPathError,
    WindowsPathPolicy,
    publish_atomic,
    sanitize_windows_filename,
    select_output_path,
    temporary_output_path,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('bad<>:"/\\|?*name. ', "bad_________name"),
        ("CON", "_CON"),
        ("lpt9.notes", "_lpt9.notes"),
        ("...   ", "media"),
        ("  normal name  ", "normal name"),
    ],
)
def test_sanitizes_windows_filename_stems(raw: str, expected: str) -> None:
    assert sanitize_windows_filename(raw) == expected


def test_conflict_policies_are_explicit_and_rename_is_deterministic(tmp_path: Path) -> None:
    directory = OutputPath(tmp_path)
    existing = tmp_path / "Title.mp4"
    existing.write_bytes(b"old")
    (tmp_path / "Title (1).mp4").write_bytes(b"older")

    renamed = select_output_path(
        directory,
        title="Title",
        extension="mp4",
        conflict_policy=ConflictPolicy.RENAME,
    )
    replaced = select_output_path(
        directory,
        title="Title",
        extension="mp4",
        conflict_policy=ConflictPolicy.REPLACE,
    )

    assert renamed.value.name == "Title (2).mp4"
    assert replaced.value == existing
    with pytest.raises(OutputConflictError):
        select_output_path(
            directory,
            title="Title",
            extension="mp4",
            conflict_policy=ConflictPolicy.SKIP,
        )


def test_atomic_publish_never_replaces_without_replace_policy(tmp_path: Path) -> None:
    final = OutputPath(tmp_path / "final.mp4")
    final.value.write_bytes(b"old")
    temporary = OutputPath(tmp_path / ".mediaflow-new.mp4")
    temporary.value.write_bytes(b"new")

    with pytest.raises(OutputConflictError):
        publish_atomic(temporary, final, conflict_policy=ConflictPolicy.RENAME)

    assert final.value.read_bytes() == b"old"
    assert temporary.value.read_bytes() == b"new"
    publish_atomic(temporary, final, conflict_policy=ConflictPolicy.REPLACE)
    assert final.value.read_bytes() == b"new"
    assert not temporary.value.exists()


def test_path_length_truncates_stem_but_preserves_suffix(tmp_path: Path) -> None:
    policy = WindowsPathPolicy(
        maximum_path_characters=len(str(tmp_path)) + 30,
        maximum_filename_characters=20,
    )
    selected = select_output_path(
        OutputPath(tmp_path),
        title="x" * 200,
        extension="mkv",
        conflict_policy=ConflictPolicy.RENAME,
        path_policy=policy,
    )

    assert selected.value.suffix == ".mkv"
    assert len(selected.value.name) <= 20
    assert len(str(selected.value)) <= policy.maximum_path_characters


def test_path_policy_rejects_directory_with_no_filename_room(tmp_path: Path) -> None:
    with pytest.raises(OutputPathError):
        select_output_path(
            OutputPath(tmp_path),
            title="title",
            extension="mp4",
            conflict_policy=ConflictPolicy.RENAME,
            path_policy=WindowsPathPolicy(
                maximum_path_characters=32,
                maximum_filename_characters=8,
            ),
        )


def test_temporary_output_is_unique_sibling_with_media_suffix(tmp_path: Path) -> None:
    final = OutputPath(tmp_path / "video.mp4")
    first = temporary_output_path(final)
    second = temporary_output_path(final)
    assert first != second
    assert first.value.parent == tmp_path
    assert first.value.suffix == ".mp4"
