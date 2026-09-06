from dataclasses import dataclass, field

from mediaflow.application import DependencyComponent, DependencyState
from mediaflow.infrastructure.media import (
    DependencyProbeOptions,
    MediaDependencyProbe,
    ProcessResult,
    ProcessTermination,
)


@dataclass(slots=True)
class FakeRunner:
    results: list[ProcessResult]
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def run(
        self,
        arguments: tuple[str, ...],
        *,
        cancellation: object,
        timeout_seconds: float,
    ) -> ProcessResult:
        del cancellation
        assert timeout_seconds == 3
        self.calls.append(arguments)
        return self.results.pop(0)


def test_dependency_probe_reports_typed_versions_and_statuses() -> None:
    runner = FakeRunner(
        [
            ProcessResult(
                ProcessTermination.EXITED,
                exit_code=0,
                stdout="ffmpeg version 7.1.2-full_build Copyright",
            ),
            ProcessResult(ProcessTermination.NOT_FOUND),
        ]
    )
    report = MediaDependencyProbe(
        runner,
        DependencyProbeOptions(
            ffmpeg_executable="C:/Tools/ffmpeg.exe",
            ffprobe_executable="C:/Tools/ffprobe.exe",
            timeout_seconds=3,
        ),
    ).probe()

    by_component = {item.component: item for item in report.dependencies}
    assert by_component[DependencyComponent.YT_DLP].state is DependencyState.READY
    assert by_component[DependencyComponent.YT_DLP].version
    assert by_component[DependencyComponent.FFMPEG].version == "7.1.2-full_build"
    assert by_component[DependencyComponent.FFPROBE].state is DependencyState.NOT_FOUND
    assert runner.calls == [
        ("C:/Tools/ffmpeg.exe", "-version"),
        ("C:/Tools/ffprobe.exe", "-version"),
    ]


def test_dependency_probe_marks_nonzero_or_unparseable_output_unusable() -> None:
    runner = FakeRunner(
        [
            ProcessResult(ProcessTermination.EXITED, exit_code=1, stderr="failed"),
            ProcessResult(ProcessTermination.EXITED, exit_code=0, stdout="unknown tool"),
        ]
    )
    report = MediaDependencyProbe(runner, DependencyProbeOptions(timeout_seconds=3)).probe()

    assert [item.state for item in report.dependencies[1:]] == [
        DependencyState.UNUSABLE,
        DependencyState.UNUSABLE,
    ]
