"""Missing environment reports never intercept the recording action with a removed dialog."""

import os
import subprocess
import sys


def test_recording_action_is_not_intercepted_by_environment_dialog(tmp_path):
    script = r'''
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from vil_logging import ui
from vil_logging.app import main
from vil_logging.runtime import Runtime
from vil_logging.contracts.models import SessionPhase
calls=[]
Runtime.discover=lambda self:None
Runtime.diagnose=lambda self,**kwargs:None
def toggle(self,roles):
    calls.append(roles)
    self._set_phase(SessionPhase.FAILED)
Runtime.toggle=toggle
class Window(ui.MainWindow):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.timer=QTimer(self)
        self.timer.timeout.connect(self.exercise)
        self.timer.start(30)
        QTimer.singleShot(8000,lambda:QApplication.instance().exit(8))
    def exercise(self):
        if self._initializing:return
        self.timer.stop()
        assert not hasattr(self.settings_dialog,'environment_button')
        assert self.settings_dialog.tabs.count()==4
        self.logging_button.click()
        assert len(calls)==1
        assert not any('EnvironmentDialog' in type(w).__name__ for w in QApplication.topLevelWidgets())
        print('NO_ENVIRONMENT_INTERCEPTION',flush=True)
        self.close()
ui.MainWindow=Window
raise SystemExit(main(['--data-dir',sys.argv[1]]))
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], capture_output=True,
                            text=True, timeout=15, env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NO_ENVIRONMENT_INTERCEPTION" in result.stdout
