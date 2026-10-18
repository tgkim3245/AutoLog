"""Exercise startup guidance and installation rechecks without vendor software."""

import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("initially_missing", [True, False])
def test_startup_and_installation_recheck(tmp_path, initially_missing):
    script = r'''
import sys
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from vil_logging.app import main
from vil_logging.runtime import Runtime
from vil_logging.diagnostics import connections
from vil_logging.ui.environment_dialog import EnvironmentDialog
from vil_logging.ui.main_window import MainWindow

missing = sys.argv[2] == "True"
stage = 0
checks = 0

def environment(self, show=True):
    status = "unavailable" if missing else "present"
    return {"canoe": {"executables": [{"path": "CANoe.exe"}]}, "dumpcap": {"version_check": {"status": status}},
            "capinfos": {"version_check": {"status": status}}}

def discover(*args):
    return {"tshark": {"status": "missing" if missing else "ready",
                       "path": "" if missing else "C:/Wireshark/tshark.exe"},
            "npcap": {"status": "missing" if missing else "present"},
            "interfaces": [], "selected_nic_id": ""}

Runtime._diagnose = environment
connections.discover_connections = discover

def verify():
    global stage, missing, checks
    checks += 1
    assert checks < 100, "startup / recheck did not finish"
    windows = QApplication.topLevelWidgets()
    view = next((w for w in windows if isinstance(w, EnvironmentDialog)), None)
    main_window = next((w for w in windows if isinstance(w, MainWindow)), None)
    if view is None or not view._environment or not view._connections:
        return
    if stage == 0:
        if not missing:
            assert not view.isVisible(), "healthy selected dependencies should not interrupt startup"
            main_window.exit_requested.emit()
            stage = 3
            return
        assert view.isVisible(), "missing tools should open guidance automatically"
        main_window.logging_requested.emit()
        assert main_window._phase.value == "idle", "missing tools must not start a session"
        view.cards["tshark"][3].click()
        assert main_window.settings_dialog.isVisible()
        assert main_window.settings_dialog.tabs.currentIndex() == 2
        assert view.cards["npcap"][3].isHidden()
        missing = False  # Dependencies installed externally; recheck without an in-app installer.
        view.refresh_button.click()
        stage = 1
    elif stage == 1 and view._connections["tshark"]["status"] == "ready" and view._environment[
            "capinfos"]["version_check"]["status"] == "present":
        assert view.cards["canoe"][1].text() == "확인됨"
        main_window.exit_requested.emit()
        stage = 3

timer = QTimer()
timer.setInterval(50)
timer.timeout.connect(verify)
initialize = Runtime.initialize
def start_checks(self):
    timer.start()
    return initialize(self)
Runtime.initialize = start_checks
result = main(["--data-dir", sys.argv[1]])
assert result == 0 and stage == 3, (result, stage)
print("readiness startup verified")
'''
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), str(initially_missing)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
        env=environment,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    assert "readiness startup verified" in result.stdout
