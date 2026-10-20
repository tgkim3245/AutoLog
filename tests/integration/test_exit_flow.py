"""Actual Qt close events and retry, with no vendor tools or physical capture."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("scenario", ["history", "stop_exception"])
def test_x_closes_with_old_history_or_after_a_failed_stop_retry(tmp_path, scenario):
    script = r'''
import sys
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from vil_logging import ui
from vil_logging.app import main
from vil_logging.runtime import Runtime
from vil_logging.contracts.models import Role, SessionPhase
from vil_logging.storage.repository import Repository
sys.path.insert(0, sys.argv[3])
from test_real_capture_policy import StubCapturePool
from test_recovery import seed

root, scenario = Path(sys.argv[1]), sys.argv[2]
if scenario == 'history':
    repo = Repository(root / 'state.sqlite3')
    output = root / 'captures'
    output.mkdir()
    plan = seed(repo, output)
    repo.close()

instances, warnings = [], []
initialize = Runtime.__init__
def create(self, *args, **kwargs):
    initialize(self, *args, **kwargs)
    self._pool.close(abnormal=True)
    self._pool = StubCapturePool()
    instances.append(self)
Runtime.__init__ = create
start_initialization = Runtime.initialize
def initialize_and_track(self):
    self.test_initialization = start_initialization(self)
    return self.test_initialization
Runtime.initialize = initialize_and_track
Runtime.discover = lambda self: None
Runtime._diagnose = lambda self, show=True: {}
stop = Runtime._stop
attempts = []
def stop_once_fails(self, *args, **kwargs):
    attempts.append(True)
    if len(attempts) == 1:
        self._set_phase(SessionPhase.STOPPING)
        raise OSError('injected stop failure')
    return stop(self, *args, **kwargs)
if scenario == 'stop_exception':
    Runtime._stop = stop_once_fails

def warning(window, title, message):
    warnings.append(message)
    assert 'X' in message and len(warnings) == 1
    QTimer.singleShot(0, window.close)
QMessageBox.warning = staticmethod(warning)

class ExercisedWindow(ui.MainWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stage = 0
        self.check = QTimer(self)
        self.check.timeout.connect(self.exercise)
        self.check.start(30)
        QTimer.singleShot(12000, lambda: QApplication.instance().exit(3))

    def exercise(self):
        if not instances or not getattr(instances[0], 'test_initialization', None):
            return
        if not instances[0].test_initialization.done():
            return
        runtime = instances[0]
        if self.stage == 0:
            self.stage = 1
            if scenario == 'history':
                self.check.stop()
                assert runtime.phase == SessionPhase.INCOMPLETE
                self.close()
            else:
                runtime.toggle((Role.ETHERNET,))
        elif runtime.phase == SessionPhase.RECORDING:
            self.check.stop()
            self.close()

ui.MainWindow = ExercisedWindow
result = main(['--data-dir', str(root)])
assert result == 0 and instances[0]._closed, (result, instances[0].phase)
assert len(warnings) == (1 if scenario == 'stop_exception' else 0)
if scenario == 'stop_exception':
    assert len(attempts) == 2
    assert instances[0]._plan.files[0].final_path.is_file()
else:
    assert plan.files[0].temp_path.is_file()
print('X_EXIT_PASSED')
'''
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), scenario, str(Path(__file__).parent)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "X_EXIT_PASSED" in result.stdout
