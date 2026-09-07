"""Configure Qt before pytest-qt creates the process QApplication."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
