"""Shared packaged/source application identity."""

import sys
from pathlib import Path

from PySide6.QtGui import QIcon


def application_icon():
    root = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3]
    return QIcon(str(root / "assets/one_click_log.ico"))
