"""Click the real main button through cancellation, recording, restart and X exit."""

import os
import subprocess
import sys


def test_main_button_controls_the_application_state_machine(tmp_path):
    script = r'''
import sys
import time
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from vil_logging import ui
from vil_logging.app import main
from vil_logging.runtime import Runtime
from vil_logging.contracts.commands import FakeBehavior
from vil_logging.contracts.models import Role, SessionPhase

create = Runtime.__init__
instances = []
def controlled(self, *args, **kwargs):
    kwargs['behaviors'] = {role: FakeBehavior(start_delay=.5, stop_delay=.15) for role in Role}
    create(self, *args, **kwargs)
    instances.append(self)
Runtime.__init__ = controlled
Runtime.discover = lambda self: None
outcome = {'step':0, 'error':''}

class ExercisedWindow(ui.MainWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.exercise = QTimer(self)
        self.exercise.setInterval(30)
        self.exercise.timeout.connect(self.advance)
        self.exercise.start()
        QTimer.singleShot(14000, lambda: QApplication.instance().exit(3))

    def advance(self):
        try:
            button = self.logging_button
            step = outcome['step']
            if step == 0 and self._settings.output_dir and not self._initializing and button.isEnabled():
                button.click()
                assert self._phase == SessionPhase.PREPARING and '취소' in button.text()
                outcome['step'] = 1
            elif step == 1 and self._phase == SessionPhase.STARTING:
                button.click()
                assert '취소 처리 중' in button.text() and not button.isEnabled()
                outcome['step'] = 2
            elif step == 2 and self._phase == SessionPhase.FAILED:
                assert button.isEnabled() and '새 기록 시작' in button.text()
                button.click()
                outcome['step'] = 3
            elif step == 3 and self._phase == SessionPhase.RECORDING:
                instances[0]._publish('phase', SessionPhase.STARTING)
                self.stale_check_after = time.monotonic() + .25
                outcome['step'] = 30
            elif step == 30 and time.monotonic() >= self.stale_check_after:
                assert self._phase == SessionPhase.RECORDING, 'Delayed phase notification regressed the button'
                assert button.property('tone') == 'stop' and '정지' in button.text()
                button.click()
                assert self._phase == SessionPhase.STOPPING and not button.isEnabled()
                outcome['step'] = 4
            elif step == 4 and self._phase == SessionPhase.COMPLETED:
                assert button.property('tone') == 'success' and button.isEnabled()
                button.click()
                outcome['step'] = 5
            elif step == 5 and self._phase == SessionPhase.RECORDING:
                self.exercise.stop()
                self.close()
                assert '종료 준비 중' in button.text() and not button.isEnabled()
                outcome['step'] = 6
        except Exception as error:
            outcome['error'] = repr(error)
            self.exercise.stop()
            QApplication.instance().exit(5)

ui.MainWindow = ExercisedWindow
result = main(['--demo', '--data-dir', sys.argv[1]])
assert result == 0 and outcome['step'] == 6, (result, outcome)
print('CAPTURE_BUTTON_FLOW_PASSED')
'''
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CAPTURE_BUTTON_FLOW_PASSED" in result.stdout
