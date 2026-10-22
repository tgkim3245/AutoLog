"""Native handles keep PID reuse or unrelated process names out of X cleanup."""

import subprocess
import sys

import pytest

from vil_logging.workers.owned_canoe import OwnedCanoe


def child():
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"],
                            creationflags=subprocess.CREATE_NO_WINDOW)


def test_remember_rejects_a_non_canoe_process_without_terminating_it():
    process = child()
    owned = OwnedCanoe()
    try:
        with pytest.raises(ValueError, match="Refusing a process"):
            owned.remember(process.pid)
        owned.terminate()
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(3)


def test_termination_uses_held_handles_and_leaves_other_processes_alive():
    import win32api

    first, other = child(), child()
    owned = OwnedCanoe()
    owned._handles[first.pid] = win32api.OpenProcess(0x00101001, False, first.pid)
    try:
        owned.terminate()
        first.wait(3)
        assert other.poll() is None
        owned.terminate()  # Idempotent; no broad image-name kill.
        assert other.poll() is None
    finally:
        for process in (first, other):
            if process.poll() is None:
                process.terminate()
            process.wait(3)
