from pathlib import Path

from mediaflow.application import ApplicationFacade
from mediaflow.bootstrap import BootstrapConfig, build_runtime


def test_composition_root_builds_and_closes_runtime_without_presentation(tmp_path: Path) -> None:
    data = (tmp_path / "data").resolve()
    output = (tmp_path / "downloads").resolve()

    runtime = build_runtime(BootstrapConfig(data, output))
    assert isinstance(runtime.facade, ApplicationFacade)
    assert runtime.facade.downloads().items == ()
    report = runtime.shutdown()

    assert report.clean
    assert (data / "mediaflow.db").is_file()
