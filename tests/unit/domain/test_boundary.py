import subprocess
import sys
from pathlib import Path


def test_domain_imports_without_framework_or_infrastructure(tmp_path: Path) -> None:
    command = """
import sys
import mediaflow.domain
forbidden = ("PySide6", "yt_dlp", "sqlite3")
assert not any(name == prefix or name.startswith(prefix + ".")
               for name in sys.modules for prefix in forbidden)
"""
    subprocess.run(
        [sys.executable, "-I", "-c", command],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
