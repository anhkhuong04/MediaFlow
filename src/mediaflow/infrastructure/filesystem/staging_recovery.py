"""Filesystem-backed recovery metadata and conservative cleanup."""

import json
import os
import shutil
from pathlib import Path

from mediaflow.application import CleanupDisposition, DownloadArtifact
from mediaflow.domain import DownloadTask, OutputPath, StreamKind

_MANIFEST_NAME = "artifact.json"


def write_artifact_manifest(directory: Path, artifact: DownloadArtifact) -> None:
    """Atomically persist only normalized, relative artifact facts."""

    root = directory.resolve(strict=False)
    relative_paths = []
    for output_path in artifact.paths:
        path = output_path.value.resolve(strict=False)
        if not path.is_relative_to(root):
            raise ValueError("Artifact path is outside its staging directory")
        relative_paths.append(str(path.relative_to(root)))
    payload = {
        "version": 1,
        "paths": relative_paths,
        "requires_processing": artifact.requires_processing,
        "stream_kinds": [kind.value for kind in artifact.stream_kinds],
    }
    temporary = root / f"{_MANIFEST_NAME}.tmp"
    manifest = root / _MANIFEST_NAME
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=True, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, manifest)


class StagingRecoveryStore:
    """Never infer completed inputs: processing recovery requires a manifest."""

    def has_resumable_partial(self, task: DownloadTask) -> bool:
        directory = _attempt_directory(task)
        if not directory.is_dir():
            return False
        return any(
            path.is_file() and ".part" in path.name and path.stat().st_size > 0
            for path in directory.iterdir()
        )

    def load_processing_artifact(self, task: DownloadTask) -> DownloadArtifact | None:
        directory = _attempt_directory(task)
        manifest = directory / _MANIFEST_NAME
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("version") != 1:
                return None
            raw_paths = raw.get("paths")
            raw_kinds = raw.get("stream_kinds")
            requires_processing = raw.get("requires_processing")
            if (
                not isinstance(raw_paths, list)
                or not raw_paths
                or not all(isinstance(value, str) for value in raw_paths)
                or not isinstance(raw_kinds, list)
                or not all(isinstance(value, str) for value in raw_kinds)
                or not isinstance(requires_processing, bool)
            ):
                return None
            root = directory.resolve(strict=False)
            paths = tuple((root / value).resolve(strict=False) for value in raw_paths)
            if any(
                not path.is_relative_to(root) or not path.is_file() or path.stat().st_size <= 0
                for path in paths
            ):
                return None
            kinds = tuple(StreamKind(value) for value in raw_kinds)
            return DownloadArtifact(
                tuple(OutputPath(path) for path in paths),
                requires_processing=requires_processing,
                stream_kinds=kinds,
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def cleanup(self, task: DownloadTask, disposition: CleanupDisposition) -> None:
        # Retention is deliberate for every non-success state so retry/recovery
        # data cannot be lost merely because an operation stopped.
        if disposition is not CleanupDisposition.SUCCESS:
            return
        directory = _attempt_directory(task)
        staging_root = (
            task.request.output_directory.value / ".mediaflow-staging" / str(task.task_id)
        ).resolve(strict=False)
        resolved = directory.resolve(strict=False)
        if resolved.parent != staging_root:
            raise ValueError("Refusing cleanup outside task staging root")
        if resolved.exists():
            shutil.rmtree(resolved)


def _attempt_directory(task: DownloadTask) -> Path:
    return (
        task.request.output_directory.value
        / ".mediaflow-staging"
        / str(task.task_id)
        / str(task.current_attempt.attempt_id)
    )
