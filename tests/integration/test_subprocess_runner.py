"""Real child-process checks using Python itself as the controlled fake executable."""

import sys

from mediaflow.infrastructure.media import ProcessTermination, SubprocessRunner


class NeverCancelled:
    def is_cancelled(self) -> bool:
        return False


class CancelAfterStart:
    def __init__(self) -> None:
        self._checks = 0

    def is_cancelled(self) -> bool:
        self._checks += 1
        return self._checks >= 3


def test_runner_preserves_argument_boundaries_and_captures_both_streams() -> None:
    result = SubprocessRunner(poll_interval_seconds=0.02).run(
        (
            sys.executable,
            "-c",
            "import sys; print(sys.argv[1]); print('problem', file=sys.stderr)",
            "value with spaces & metacharacters",
        ),
        cancellation=NeverCancelled(),
        timeout_seconds=5,
    )

    assert result.succeeded
    assert result.exit_code == 0
    assert "value with spaces & metacharacters" in result.stdout
    assert "problem" in result.stderr


def test_runner_returns_stderr_failure_without_raising() -> None:
    result = SubprocessRunner().run(
        (
            sys.executable,
            "-c",
            "import sys; print('controlled failure', file=sys.stderr); raise SystemExit(7)",
        ),
        cancellation=NeverCancelled(),
        timeout_seconds=5,
    )
    assert result.termination is ProcessTermination.EXITED
    assert result.exit_code == 7
    assert result.stderr.strip() == "controlled failure"
    assert not result.succeeded


def test_runner_enforces_timeout_and_reaps_process() -> None:
    result = SubprocessRunner(poll_interval_seconds=0.01).run(
        (sys.executable, "-c", "import time; time.sleep(30)"),
        cancellation=NeverCancelled(),
        timeout_seconds=0.05,
    )
    assert result.termination is ProcessTermination.TIMED_OUT


def test_runner_cooperatively_cancels_and_reaps_process() -> None:
    result = SubprocessRunner(poll_interval_seconds=0.01).run(
        (sys.executable, "-c", "import time; time.sleep(30)"),
        cancellation=CancelAfterStart(),
        timeout_seconds=5,
    )
    assert result.termination is ProcessTermination.CANCELLED


def test_runner_reports_missing_executable() -> None:
    result = SubprocessRunner().run(
        ("mediaflow-command-that-does-not-exist", "-version"),
        cancellation=NeverCancelled(),
        timeout_seconds=1,
    )
    assert result.termination is ProcessTermination.NOT_FOUND
