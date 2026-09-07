from pathlib import Path
from threading import Thread
from threading import enumerate as enumerate_threads

import pytest
from PySide6.QtWidgets import QApplication

from mediaflow.bootstrap import BootstrapConfig
from mediaflow.presentation import (
    MediaFlowWindow,
    UiThreadViolation,
    assert_ui_thread,
    build_desktop_runtime,
)
from mediaflow.presentation.entrypoint import create_application, default_bootstrap_config
from mediaflow.presentation.resources import resource_directory, resource_path


def test_desktop_runtime_opens_and_closes_owned_shell(
    qtbot: object, qapp: QApplication, tmp_path: Path
) -> None:
    runtime = build_desktop_runtime(
        BootstrapConfig(
            data_directory=(tmp_path / "data").resolve(),
            default_output_directory=(tmp_path / "downloads").resolve(),
        ),
        application=qapp,
    )
    try:
        _add_widget(qtbot, runtime.window)
        runtime.show()

        assert runtime.window.isVisible()
        assert_ui_thread(runtime.window)

        runtime.shutdown()

        assert runtime.is_shutdown
        assert not runtime.window.isVisible()
        assert not any(widget.isVisible() for widget in qapp.topLevelWidgets())
        assert not any(
            thread.is_alive() and thread.name.startswith("mediaflow-")
            for thread in enumerate_threads()
        )
        assert (tmp_path / "data" / "mediaflow.db").is_file()
    finally:
        runtime.shutdown()


def test_ui_thread_guard_rejects_foreign_widget_access(qtbot: object) -> None:
    window = MediaFlowWindow()
    _add_widget(qtbot, window)
    violations: list[BaseException] = []

    def access_from_worker() -> None:
        try:
            assert_ui_thread(window)
        except UiThreadViolation as error:
            violations.append(error)

    worker = Thread(target=access_from_worker, name="mediaflow-ui-guard-test")
    worker.start()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert len(violations) == 1


def test_resource_paths_are_package_relative_and_standard_locations_are_absolute(
    qapp: QApplication,
) -> None:
    del qapp
    config = default_bootstrap_config()

    assert config.data_directory.is_absolute()
    assert config.default_output_directory.is_absolute()
    assert resource_path("icons/mediaflow.svg").is_relative_to(resource_directory())
    with pytest.raises(ValueError):
        resource_path("../outside-package.svg")


def test_application_factory_reuses_the_existing_qapplication(qapp: QApplication) -> None:
    assert create_application(["mediaflow-test"]) is qapp


def _add_widget(qtbot: object, widget: MediaFlowWindow) -> None:
    add_widget = getattr(qtbot, "addWidget", None)
    if add_widget is None:
        pytest.fail("pytest-qt did not provide qtbot.addWidget")
    add_widget(widget)
