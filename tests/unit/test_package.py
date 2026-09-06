"""Verify the installed package, without modifying sys.path."""

import subprocess
import sys
from pathlib import Path


def test_installed_import_has_no_side_effects(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-I", "-c", "import mediaflow"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert result.stdout == result.stderr == ""
    assert list(tmp_path.iterdir()) == []
