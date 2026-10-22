"""A stuck/partial worker IPC read must never block the main window or X."""

import queue
import threading
from types import SimpleNamespace

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QSystemTrayIcon

from vil_logging.ui.main_window import MainWindow
from vil_logging.workers.packet_bridge import PacketBridge


def test_stalled_transport_keeps_ui_and_close_responsive(qtbot, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    class StalledTransport:
        def get(self, **kwargs):
            entered.set()
            release.wait(5)
            raise EOFError

    bridge = PacketBridge(StalledTransport())
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    spy = QSignalSpy(window.exit_requested)
    try:
        qtbot.waitUntil(entered.is_set)
        assert bridge.drain() == []
        window.close()
        assert spy.count() == 1
        bridge.close()  # Does not wait for the stuck transport.
        assert bridge._reader.is_alive()
    finally:
        release.set()
        bridge.close()


def test_bounded_display_keeps_latest_and_counts_drops_per_session(qtbot):
    source = queue.Queue()
    bridge = PacketBridge(source, capacity=3)
    try:
        for session, number in (("old", 1), ("old", 2), ("new", 3), ("new", 4), ("new", 5)):
            source.put(SimpleNamespace(session_id=session, number=number))
        qtbot.waitUntil(lambda: bridge.dropped("old") == 2)
        assert bridge.dropped("new") == 0
        assert [row.number for row in bridge.drain(2)] == [3, 4]
        assert [row.number for row in bridge.drain()] == [5]
        assert bridge.drain() == []
    finally:
        bridge.close()
