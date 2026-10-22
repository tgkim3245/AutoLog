"""Verify real process exit while coordinator or background work is stuck."""

import json
import os
import subprocess
import sys
import time

import pytest


@pytest.mark.parametrize("scenario", ["initializing", "recording", "diagnostics", "repeat"])
def test_x_always_exits_and_terminates_owned_workers(tmp_path, scenario):
    script = r'''
import json,sys,threading,time
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from vil_logging import ui
from vil_logging.app import main
from vil_logging.runtime import Runtime
from vil_logging.contracts.models import SessionPhase

root,scenario=Path(sys.argv[1]),sys.argv[2]
instances=[]
create=Runtime.__init__
def collect(self,*args,**kwargs):
    create(self,*args,**kwargs)
    instances.append(self)
Runtime.__init__=collect
Runtime.discover=lambda self: None
if scenario in {'initializing','repeat'}:
    Runtime._initialize=lambda self: threading.Event().wait(60)
elif scenario=='recording':
    def blocked_stop(self,*args,**kwargs):
        (root/'blocked-stop-called').touch()
        self._set_phase(SessionPhase.STOPPING)
        threading.Event().wait(60)
    Runtime._stop=blocked_stop
elif scenario=='diagnostics':
    Runtime.discover=lambda self:self._background(lambda:threading.Event().wait(60),lambda result:None)

class ExercisedWindow(ui.MainWindow):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.stage=0
        self.exercise=QTimer(self)
        self.exercise.timeout.connect(self.advance)
        self.exercise.start(30)
        QTimer.singleShot(12000,lambda:QApplication.instance().exit(9))

    def advance(self):
        if not instances:return
        runtime=instances[0]
        if scenario=='recording':
            if self.stage==0 and runtime._ready:
                self.stage=1
                runtime.toggle(self.selected_roles())
            if runtime.phase!=SessionPhase.RECORDING:return
        elif scenario=='resume' and self._initializing:
            return
        self.exercise.stop()
        if scenario=='resume':
            (root/'startup-marker-cleared.json').write_text(json.dumps({'cleared':not (root/'One_Click_Log_force_exit.json').exists()}))
        (root/'exit-request.json').write_text(json.dumps({'at':time.time(),'workers':[p.pid for p in runtime._pool._processes.values()]}))
        self.close()
        if scenario=='repeat':QTimer.singleShot(100,self.close)

ui.MainWindow=ExercisedWindow
raise SystemExit(main(['--demo','--data-dir',str(root)]))
'''
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), scenario], env=env,
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    request = json.loads((tmp_path / "exit-request.json").read_text())
    assert time.time() - request["at"] < (2 if scenario == "repeat" else 5)
    marker = tmp_path / "One_Click_Log_force_exit.json"
    if scenario != "recording":
        notice = json.loads(marker.read_text(encoding="utf-8"))
        assert notice["reason"] == ("repeat_close" if scenario == "repeat" else "deadline")
    else:
        assert not (tmp_path / "blocked-stop-called").exists()
        # A slow filesystem may use the bounded fallback; X must never invoke Stop.
        if marker.exists():
            assert json.loads(marker.read_text(encoding="utf-8"))["reason"] == "deadline"
    if os.name == "nt":
        import pywintypes
        import win32api
        import win32event
        for pid in request["workers"]:
            try:
                handle = win32api.OpenProcess(0x100000, False, pid)
            except pywintypes.error as error:
                assert error.winerror == 87  # The owned worker has already disappeared.
                continue
            try:
                assert win32event.WaitForSingleObject(handle, 1000) == win32event.WAIT_OBJECT_0
            finally:
                handle.Close()
    if scenario == "recording":
        resumed = subprocess.run([sys.executable, "-c", script, str(tmp_path), "resume"], env=env,
                                 capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
        assert resumed.returncode == 0, resumed.stdout + resumed.stderr
        assert json.loads((tmp_path / "startup-marker-cleared.json").read_text())["cleared"]
