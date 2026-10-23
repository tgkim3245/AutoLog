"""Fresh startup routes to setup; only checked targets can emit a real start."""

import os
import subprocess
import sys


def test_unconfigured_startup_opens_settings_then_allows_start_after_preparation(tmp_path):
    script = r'''
import sys
from dataclasses import replace
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from vil_logging import ui
from vil_logging.app import main
from vil_logging.runtime import Runtime
from vil_logging.contracts.models import ConnectionState, Role, SessionPhase, TargetSnapshot
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
        assert self.logging_button.text()=='환경 설정 필요'
        self.logging_button.click()
        assert not calls and self.settings_dialog.isVisible()
        assert self.settings_dialog.tabs.currentIndex()==1
        self.settings_dialog.hide()
        self.set_settings(replace(self._settings,can_cfg='C:/example/CAN.cfg',can_logging_block='1',nic_id='example-nic'))
        for role in (Role.CAN,Role.ETHERNET):
            self.set_target(TargetSnapshot(role,connection=ConnectionState.READY))
        assert self.logging_button.property('tone')=='success'
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
