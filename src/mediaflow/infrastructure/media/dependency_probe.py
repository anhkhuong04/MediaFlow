"""Typed availability checks for the media engine dependencies."""

import re
from dataclasses import dataclass

from yt_dlp.version import __version__ as yt_dlp_version  # type: ignore[import-untyped]

from mediaflow.application import (
    DependencyComponent,
    DependencyInfo,
    DependencyReport,
    DependencyState,
)
from mediaflow.infrastructure.media.process_runner import (
    ProcessRunner,
    ProcessTermination,
)

_VERSION_PATTERN = re.compile(r"\bversion\s+([^\s]+)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class DependencyProbeOptions:
    ffmpeg_executable: str = "ffmpeg"
    ffprobe_executable: str = "ffprobe"
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        for executable in (self.ffmpeg_executable, self.ffprobe_executable):
            if not executable or "\0" in executable:
                raise ValueError("Dependency executable must be non-empty")
        if self.timeout_seconds <= 0:
            raise ValueError("Dependency probe timeout must be positive")


@dataclass(frozen=True, slots=True)
class MediaDependencyProbe:
    runner: ProcessRunner
    options: DependencyProbeOptions = DependencyProbeOptions()

    def probe(self) -> DependencyReport:
        return DependencyReport(
            (
                DependencyInfo(
                    DependencyComponent.YT_DLP,
                    DependencyState.READY,
                    yt_dlp_version,
                ),
                self._probe_executable(DependencyComponent.FFMPEG, self.options.ffmpeg_executable),
                self._probe_executable(
                    DependencyComponent.FFPROBE, self.options.ffprobe_executable
                ),
            )
        )

    def _probe_executable(self, component: DependencyComponent, executable: str) -> DependencyInfo:
        result = self.runner.run(
            (executable, "-version"),
            cancellation=_NeverCancelled(),
            timeout_seconds=self.options.timeout_seconds,
        )
        if result.termination is ProcessTermination.NOT_FOUND:
            return DependencyInfo(component, DependencyState.NOT_FOUND)
        if not result.succeeded:
            return DependencyInfo(component, DependencyState.UNUSABLE)
        match = _VERSION_PATTERN.search(result.stdout) or _VERSION_PATTERN.search(result.stderr)
        if match is None:
            return DependencyInfo(component, DependencyState.UNUSABLE)
        return DependencyInfo(component, DependencyState.READY, match.group(1))


@dataclass(frozen=True, slots=True)
class _NeverCancelled:
    def is_cancelled(self) -> bool:
        return False
