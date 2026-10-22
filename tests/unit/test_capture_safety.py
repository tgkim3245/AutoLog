"""Link status and native exit ownership regression checks without vendor hardware."""

import queue
import subprocess
import sys
from types import SimpleNamespace

import pytest

from vil_logging.adapters.tshark import TSharkCapture
from vil_logging.diagnostics import network_activity
from vil_logging.workers import owned_canoe


@pytest.mark.parametrize("status,expected", [(1, "connected"), (2, "disconnected"), (6, "disconnected"),
                                           (7, "disconnected"), (4, "unknown"), (5, "unknown")])
def test_selected_nic_link_status_is_not_inferred_from_packet_silence(monkeypatch, status, expected):
    monkeypatch.setattr(network_activity, "read_receive_counters", lambda: (0, {
        "nic": network_activity.ReceiveCounter(0, 1, status),
        "other": network_activity.ReceiveCounter(9999, 2, 1)}))
    assert network_activity.capture_link_state("nic")["state"] == expected
    assert network_activity.capture_link_state("removed")["state"] == "disconnected"


def test_live_dumpcap_reports_disconnected_nic_without_preventing_normal_stop(monkeypatch):
    capture = TSharkCapture(queue.Queue())
    capture.process = SimpleNamespace(poll=lambda: None)
    capture.binding = {"nic_id": "selected"}
    capture._started = True
    monkeypatch.setattr(capture, "stats", lambda: {"session_id": "active"})
    monkeypatch.setattr("vil_logging.adapters.tshark.capture_link_state", lambda nic: {"state": "disconnected"})
    state, details = capture.query()
    assert state == "recording"  # Recorder still runs; the coordinator requests a clean stop.
    assert details["link"]["state"] == "disconnected"


def test_native_creation_time_can_register_and_signal_without_win32timezone(monkeypatch):
    process = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(20)"],
                               creationflags=subprocess.CREATE_NO_WINDOW)
    other = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(20)"],
                             creationflags=subprocess.CREATE_NO_WINDOW)
    owned = owned_canoe.OwnedCanoe()
    # Only substitute the image allow-list result. All native handle/FILETIME and
    # termination calls operate on this test's private child processes.
    monkeypatch.setattr(owned_canoe, "Path", lambda _: SimpleNamespace(name="CANoe64.exe"))
    monkeypatch.setitem(sys.modules, "win32timezone", None)
    try:
        owned.remember(process.pid)
        assert process.pid in owned._handles
        owned.terminate()
        process.wait(3)
        assert other.poll() is None
        # An activation that finishes after X receives termination immediately too.
        owned.remember(other.pid)
        other.wait(3)
        assert not owned._handles
    finally:
        owned.terminate()
        for child in (process, other):
            if child.poll() is None:
                child.terminate()
            child.wait(3)
