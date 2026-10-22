"""Exercise a full visible packet table repeatedly, including X, without vendor tools."""

import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("mode", ["repeat", "streaming"])
def test_full_packet_view_remains_responsive_and_main_x_is_delivered(mode):
    script = r'''
import sys,time
from PySide6.QtCore import QTimer
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication
from vil_logging.ui.main_window import MainWindow
from vil_logging.contracts.models import PacketSummary
app = QApplication([])
window = MainWindow()
window.show()
spy = QSignalSpy(window.exit_requested)
started = time.monotonic()
for i in range(1000):
    window.add_packet(PacketSummary(str(i), '2001:db8::1', '2001:db8::2', 'UDP', 1514))
steps = []
def exercise():
    i = len(steps)
    if sys.argv[1] == 'streaming':
        for n in range(100):
            window.add_packet(PacketSummary(str(1000+i*100+n), '2001:db8::3', '2001:db8::4', 'TCP', 1514))
    window.packet_window.show()
    window.packet_window.refresh()
    assert window.packet_window.model.rowCount() == 1000
    if sys.argv[1] == 'repeat':
        window.packet_window.hide()
    steps.append(i)
    if i < (39 if sys.argv[1] == 'streaming' else 4):
        QTimer.singleShot(20, exercise)
    else:
        window.close()
        assert spy.count() == 1
        app.exit(0)
QTimer.singleShot(0, exercise)
QTimer.singleShot(5000, lambda: app.exit(3))
assert app.exec() == 0
assert time.monotonic() - started < 3
print('PACKET_VIEW_RESPONSIVE')
'''
    result = subprocess.run([sys.executable, "-c", script, mode], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=10,
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONDONTWRITEBYTECODE": "1"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PACKET_VIEW_RESPONSIVE" in result.stdout
