"""Fault injection for production state/file policy; opens no NIC or external tool."""

import struct

import pytest

from vil_logging.contracts.commands import Command, CommandResult
from vil_logging.contracts.models import Role, SessionPhase
from vil_logging.runtime import Runtime


class StubCapturePool:
    def __init__(self):
        self.calls = []
        self.fault = ""
        self.path = None
        self.after_stop = self.after_inspect = lambda: None

    def request(self, roles, action, session_id, **kwargs):
        self.calls.append(action)
        results = {}
        for role in roles:
            details = {}
            success = True
            if action == "prepare":
                success, state = self.fault != "prepare", "ready"
            elif action == "start":
                from pathlib import Path
                self.path = Path(kwargs["params"]["temp_path"])
                self.path.write_bytes(struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1))
                state = "recording"
            elif action == "stop":
                self.after_stop()
                success, state = self.fault != "stop", "stopped" if self.fault != "stop" else "unknown"
            elif action == "inspect":
                success, state = self.fault != "inspect", "verified"
                value = self.path.stat()
                details = {"bytes": value.st_size, "mtime_ns": value.st_mtime_ns, "inode": value.st_ino,
                           "packet_count": 0, "actual_format": "pcap"}
                self.after_inspect()
            else:
                state = "stopped"
            results[role] = CommandResult(Command(action, role, session_id), success, state,
                                           "injected policy evidence", details=details)
        return results

    def close(self, **_kwargs):
        pass

    def drain_packets(self):
        return []


@pytest.fixture
def real(tmp_path):
    runtime = Runtime(tmp_path)
    runtime.initialize().result(timeout=5)
    runtime._pool.close(abnormal=True)
    pool = StubCapturePool()
    runtime._pool = pool
    yield runtime, pool
    runtime.close_for_test()


def test_real_start_reserves_once_and_normal_stop_verifies_then_publishes(real):
    runtime, pool = real
    runtime.toggle((Role.ETHERNET,)).result(timeout=5)
    assert runtime.phase == SessionPhase.RECORDING and runtime._settings.next_index == 2
    file = runtime._plan.files[0]
    assert file.temp_path.is_file() and not file.final_path.exists()
    runtime.toggle((Role.ETHERNET,)).result(timeout=5)
    assert runtime.phase == SessionPhase.COMPLETED
    assert pool.calls == ["prepare", "start", "stop", "inspect"]
    assert file.final_path.is_file() and not file.temp_path.exists()
    assert not file.temp_path.parent.exists()
    assert not file.temp_path.parent.parent.exists()
    assert runtime._settings.next_index == 2


def test_prepare_failure_never_reserves_or_starts(real):
    runtime, pool = real
    pool.fault = "prepare"
    runtime.toggle((Role.ETHERNET,)).result(timeout=5)
    assert runtime._settings.next_index == 1 and runtime._plan is None
    assert pool.calls == ["prepare"]


def test_reservation_failure_never_sends_start(real, monkeypatch):
    runtime, pool = real

    def reject(_plan):
        raise OSError("injected DB failure")

    monkeypatch.setattr(runtime._repo, "reserve", reject)
    runtime.toggle((Role.ETHERNET,)).result(timeout=5)
    assert runtime._settings.next_index == 1 and "start" not in pool.calls


def test_existing_output_blocks_capture_before_prepare(real):
    runtime, pool = real
    existing = runtime.data_dir / "captures/AutoLog_1.pcap"
    existing.write_bytes(b"precious original")
    runtime.toggle((Role.ETHERNET,)).result(timeout=5)
    assert not pool.calls and runtime._settings.next_index == 1
    assert existing.read_bytes() == b"precious original"


def test_unconfirmed_stop_keeps_working_file_and_blocks_restart_and_exit(real):
    runtime, pool = real
    runtime.toggle((Role.ETHERNET,)).result(timeout=5)
    pool.fault = "stop"
    runtime.toggle((Role.ETHERNET,)).result(timeout=5)
    assert runtime.phase == SessionPhase.INCOMPLETE
    assert runtime._plan.files[0].temp_path.is_file()
    assert runtime._plan.files[0].temp_path.parent.is_dir()
    assert not runtime._plan.files[0].final_path.exists()
    assert runtime.toggle((Role.ETHERNET,)) is None
    assert runtime.request_exit().result(timeout=5) is False
    pool.fault = ""
    assert runtime.request_exit().result(timeout=5) is True  # Explicit exit retries owned stop.


@pytest.mark.parametrize("fault", ["inspect", "collision", "changed"])
def test_failed_verification_or_publish_preserves_working_capture(real, fault):
    runtime, pool = real
    runtime.toggle((Role.ETHERNET,)).result(timeout=5)
    file = runtime._plan.files[0]
    if fault == "collision":
        pool.after_stop = lambda: file.final_path.write_bytes(b"precious original")
    elif fault == "changed":
        pool.after_inspect = lambda: file.temp_path.write_bytes(b"changed by another process")
    else:
        pool.fault = "inspect"
    runtime.toggle((Role.ETHERNET,)).result(timeout=5)
    assert runtime.phase == SessionPhase.FAILED and file.temp_path.is_file()
    assert file.temp_path.parent.is_dir()
    assert runtime._settings.next_index == 2
    if fault == "collision":
        assert file.final_path.read_bytes() == b"precious original"
    else:
        assert not file.final_path.exists()


def test_commit_failure_after_move_preserves_final_and_marks_incomplete(real, monkeypatch):
    runtime, _ = real
    runtime.toggle((Role.ETHERNET,)).result(timeout=5)
    update = runtime._repo.update_capture_file

    def fail_published(session_id, role, state, **details):
        if state == "published":
            raise OSError("injected metadata failure after atomic move")
        return update(session_id, role, state, **details)

    monkeypatch.setattr(runtime._repo, "update_capture_file", fail_published)
    runtime.toggle((Role.ETHERNET,)).result(timeout=5)
    assert runtime.phase == SessionPhase.INCOMPLETE
    assert runtime._plan.files[0].final_path.is_file()
    assert runtime._storage_failed


def test_cancellation_after_reservation_sends_no_start_and_keeps_reserved_index(real, monkeypatch):
    runtime, pool = real
    reserve = runtime._repo.reserve

    def cancel_after_reserve(plan):
        settings = reserve(plan)
        runtime._cancel.set()
        return settings

    monkeypatch.setattr(runtime._repo, "reserve", cancel_after_reserve)
    runtime.toggle((Role.ETHERNET,)).result(timeout=5)
    assert runtime.phase == SessionPhase.FAILED and runtime._settings.next_index == 2
    assert "start" not in pool.calls


def test_pool_shutdown_failure_reports_exit_not_ready_instead_of_hanging_ui(real, monkeypatch):
    runtime, pool = real

    def refuse(**_kwargs):
        raise RuntimeError("Owned worker exit is unconfirmed")

    monkeypatch.setattr(pool, "close", refuse)
    assert runtime.request_exit().result(timeout=5) is False
    assert not runtime._exit_pending
    messages = []
    while not runtime.messages.empty():
        messages.append(runtime.messages.get_nowait())
    assert ("exit_ready", False) in messages
    monkeypatch.undo()
