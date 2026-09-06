"""Cancellable subprocess execution using argument arrays only."""

import subprocess
from dataclasses import dataclass
from enum import StrEnum
from time import monotonic
from typing import Protocol

from mediaflow.application import CancellationToken


class ProcessTermination(StrEnum):
    EXITED = "exited"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    NOT_FOUND = "not_found"
    START_FAILED = "start_failed"


@dataclass(frozen=True, slots=True)
class ProcessResult:
    termination: ProcessTermination
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""

    def __post_init__(self) -> None:
        if (self.termination is ProcessTermination.EXITED) != (self.exit_code is not None):
            raise ValueError("Only an exited process has an exit code")

    @property
    def succeeded(self) -> bool:
        return self.termination is ProcessTermination.EXITED and self.exit_code == 0


class ProcessRunner(Protocol):
    def run(
        self,
        arguments: tuple[str, ...],
        *,
        cancellation: CancellationToken,
        timeout_seconds: float,
    ) -> ProcessResult: ...


@dataclass(frozen=True, slots=True)
class SubprocessRunner(ProcessRunner):
    poll_interval_seconds: float = 0.1
    termination_grace_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.poll_interval_seconds <= 0 or self.termination_grace_seconds <= 0:
            raise ValueError("Process timing values must be positive")

    def run(
        self,
        arguments: tuple[str, ...],
        *,
        cancellation: CancellationToken,
        timeout_seconds: float,
    ) -> ProcessResult:
        if not arguments or any(not value or "\0" in value for value in arguments):
            raise ValueError("Process arguments must be non-empty and contain no NUL")
        if timeout_seconds <= 0:
            raise ValueError("Process timeout must be positive")
        if cancellation.is_cancelled():
            return ProcessResult(ProcessTermination.CANCELLED)
        try:
            process = subprocess.Popen(
                list(arguments),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except FileNotFoundError:
            return ProcessResult(ProcessTermination.NOT_FOUND)
        except OSError:
            return ProcessResult(ProcessTermination.START_FAILED)

        deadline = monotonic() + timeout_seconds
        while True:
            if cancellation.is_cancelled():
                stdout, stderr = self._stop(process)
                return ProcessResult(
                    ProcessTermination.CANCELLED,
                    stdout=_decode(stdout),
                    stderr=_decode(stderr),
                )
            remaining = deadline - monotonic()
            if remaining <= 0:
                stdout, stderr = self._stop(process)
                return ProcessResult(
                    ProcessTermination.TIMED_OUT,
                    stdout=_decode(stdout),
                    stderr=_decode(stderr),
                )
            try:
                stdout, stderr = process.communicate(
                    timeout=min(self.poll_interval_seconds, remaining)
                )
                return ProcessResult(
                    ProcessTermination.EXITED,
                    exit_code=process.returncode,
                    stdout=_decode(stdout),
                    stderr=_decode(stderr),
                )
            except subprocess.TimeoutExpired:
                continue

    def _stop(self, process: subprocess.Popen[bytes]) -> tuple[bytes, bytes]:
        try:
            process.terminate()
        except OSError:
            return process.communicate()
        try:
            return process.communicate(timeout=self.termination_grace_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            return process.communicate()


def _decode(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")
