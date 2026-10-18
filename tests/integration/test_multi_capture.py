"""Real coordinator policy with injected tools; no CANoe or NIC is opened."""

from pathlib import Path

import pytest

from vil_logging.contracts.commands import Command, CommandResult
from vil_logging.contracts.models import Role, SessionPhase
from vil_logging.runtime import Runtime


class Tools:
    def __init__(self):
        self.calls = []
        self.paths = {}
        self.fail = None
        self.stopped = set()
        self.connection_details = {}
        self.failure_details = {}

    def request(self, roles, action, session_id, **kwargs):
        self.calls.append((roles, action))
        result = {}
        for role in roles:
            params = kwargs.get("role_params", {}).get(role, kwargs.get("params", {}))
            details = {}
            success = (role, action) != self.fail
            state = {"connect": "ready", "prepare": "ready", "configure": "configured", "start": "recording",
                     "stop": "stopped", "restore": "stopped", "inspect": "verified", "query": "recording"}[action]
            if not success:
                state = "unknown"
                details = self.failure_details
            elif action == "connect":
                details = self.connection_details
            elif action == "configure":
                self.paths[role] = Path(params["temp_path"])
            elif action == "start":
                self.paths[role] = Path(params["temp_path"])
                self.paths[role].write_bytes(b"injected closed-file fixture")
            elif action == "stop":
                self.stopped.add(role)
            elif action == "inspect":
                assert role in self.stopped  # No inspection before each tool's normal stop.
                info = self.paths[role].stat()
                details = {"bytes": info.st_size, "mtime_ns": info.st_mtime_ns, "inode": info.st_ino,
                           "object_count": 5, "packet_count": 6, "actual_format": "blf"}
            result[role] = CommandResult(Command(action, role, session_id), success, state,
                                         "injected proof", details=details)
        return result

    def close(self, **kwargs):
        pass

    def drain_packets(self):
        return []


@pytest.fixture
def real(tmp_path):
    runtime = Runtime(tmp_path)
    runtime.initialize().result(timeout=5)
    runtime._pool.close(abnormal=True)
    tools = Tools()
    runtime._pool = tools
    runtime.save_preferences({"can_cfg": "C:/can.cfg", "diag_cfg": "C:/diag.cfg"}).result(timeout=5)
    yield runtime, tools
    runtime.close_for_test()


def test_three_roles_configure_before_reservation_and_stop_all_before_inspection(real, monkeypatch):
    runtime, tools = real
    reserve = runtime._repo.reserve

    def checked_reserve(plan):
        assert tools.calls[-1] == ((Role.CAN, Role.DIAG), "configure")
        assert not any(action == "start" for _, action in tools.calls)
        return reserve(plan)

    monkeypatch.setattr(runtime._repo, "reserve", checked_reserve)
    roles = (Role.CAN, Role.DIAG, Role.ETHERNET)
    runtime.toggle(roles).result(timeout=5)
    assert runtime.phase == SessionPhase.RECORDING and runtime._settings.next_index == 2
    assert [group for group, action in tools.calls if action == "start"] == [(Role.ETHERNET,), (Role.CAN, Role.DIAG)]
    runtime.toggle(roles).result(timeout=5)
    assert runtime.phase == SessionPhase.COMPLETED
    stop = next(i for i, (_, action) in enumerate(tools.calls) if action == "stop")
    assert tools.calls[stop][0] == (Role.ETHERNET, Role.CAN, Role.DIAG)
    assert all(i > stop for i, (_, action) in enumerate(tools.calls) if action == "inspect")
    assert all(file.final_path.is_file() for file in runtime._plan.files)


def test_canoe_output_failure_reserves_no_number_and_starts_nothing(real):
    runtime, tools = real
    tools.fail = (Role.DIAG, "configure")
    runtime.toggle((Role.CAN, Role.DIAG)).result(timeout=5)
    assert runtime.phase == SessionPhase.FAILED and runtime._settings.next_index == 1
    assert runtime._plan is None
    assert not any(action == "start" for _, action in tools.calls)
    assert tools.calls[-1] == ((Role.CAN, Role.DIAG), "restore")
    assert not (runtime.data_dir / "captures/.vil_work").exists()


def test_one_start_failure_reconciles_all_issued_targets_without_reusing_index(real):
    runtime, tools = real
    tools.fail = (Role.DIAG, "start")
    runtime.toggle((Role.CAN, Role.DIAG, Role.ETHERNET)).result(timeout=5)
    assert runtime.phase == SessionPhase.FAILED
    assert runtime._settings.next_index == 2
    assert tools.stopped == {Role.CAN, Role.DIAG, Role.ETHERNET}
    assert not next(file for file in runtime._plan.files if file.role == Role.DIAG).final_path.exists()


def test_unconfirmed_can_stop_preserves_its_file_but_archives_other_closed_targets(real):
    runtime, tools = real
    runtime.toggle((Role.CAN, Role.DIAG, Role.ETHERNET)).result(timeout=5)
    tools.fail = (Role.CAN, "stop")
    runtime.toggle((Role.CAN, Role.DIAG, Role.ETHERNET)).result(timeout=5)
    assert runtime.phase == SessionPhase.INCOMPLETE
    for file in runtime._plan.files:
        assert file.temp_path.is_file() if file.role == Role.CAN else file.final_path.is_file()


def test_same_configuration_for_can_and_diag_is_rejected_before_tool_commands(real):
    runtime, tools = real
    runtime.save_preferences({"diag_cfg": "C:/can.cfg"}).result(timeout=5)
    runtime.toggle((Role.CAN, Role.DIAG)).result(timeout=5)
    assert runtime._settings.next_index == 1 and not tools.calls


def test_reservation_error_restores_both_configured_outputs(real, monkeypatch):
    runtime, tools = real

    def reject(plan):
        raise OSError("injected storage failure")

    monkeypatch.setattr(runtime._repo, "reserve", reject)
    runtime.toggle((Role.CAN, Role.DIAG)).result(timeout=5)
    assert tools.calls[-1] == ((Role.CAN, Role.DIAG), "restore")
    assert not any(action == "start" for _, action in tools.calls)
    assert runtime._settings.next_index == 1


def test_cancel_after_configuration_restores_without_reserving(real):
    runtime, tools = real
    request = tools.request

    def cancel(roles, action, session_id, **kwargs):
        result = request(roles, action, session_id, **kwargs)
        if action == "configure":
            runtime._cancel.set()
        return result

    tools.request = cancel
    runtime.toggle((Role.CAN, Role.DIAG)).result(timeout=5)
    assert tools.calls[-1] == ((Role.CAN, Role.DIAG), "restore")
    assert runtime.phase == SessionPhase.IDLE
    assert runtime._settings.next_index == 1
    assert not any(action == "start" for _, action in tools.calls)


@pytest.mark.parametrize("view_only", [True, False])
def test_connection_report_separates_license_failure_from_managed_filename_options(real, view_only):
    runtime, tools = real
    tools.connection_details = {"selected_block": "1", "measurement_running": True, "trigger_active": False,
                                "view_only": view_only, "automatic_splitting": ["IncrementAfterTrigger"],
                                "blocks": [{"id": "1", "name": "CAN_Logging", "format": "blf"}]}
    runtime._submit(runtime._prepare_canoe, Role.CAN).result(timeout=5)
    reports = []
    while not runtime.messages.empty():
        kind, value = runtime.messages.get_nowait()
        if kind == "preparation":
            reports.append(value)
    report = reports[-1]
    assert report["selected_block"] == "1" and report["blocks"][0]["name"] == "CAN_Logging"
    assert report["status"] == ("attention" if view_only else "ready")
    if view_only:
        assert "라이선스" in report["message_ko"]
    else:
        assert "기존 로깅 버튼" in report["next_action_ko"]


def test_running_shared_mode_requests_only_one_time_close_without_a_mode_choice(real):
    runtime, tools = real
    tools.fail = (Role.DIAG, "connect")
    tools.failure_details = {"connection_issue": "restart_required",
                             "diagnostics": [{"event": "canoe.activation_failed"}]}
    runtime._submit(runtime._prepare_canoe, Role.DIAG).result(5)
    reports = []
    while not runtime.messages.empty():
        kind, value = runtime.messages.get_nowait()
        if kind == "preparation":
            reports.append(value)
    report = reports[-1]
    assert report["status"] == "attention" and "action" not in report
    assert "자동 적용" in report["detail"]
    assert "Traceback" not in report["detail"]
    assert report["diagnostic_detail"] == "injected proof"
    assert tools.calls == [((Role.DIAG,), "connect")]


def test_old_reused_instance_journal_never_masks_a_new_unrelated_connection_error(real):
    runtime, tools = real
    tools.fail = (Role.DIAG, "connect")
    tools.failure_details = {"diagnostics": [{"event": "canoe.independent_setup_required"}]}
    runtime._submit(runtime._prepare_canoe, Role.DIAG).result(5)
    reports = []
    while not runtime.messages.empty():
        kind, value = runtime.messages.get_nowait()
        if kind == "preparation":
            reports.append(value)
    assert reports[-1]["status"] == "error" and "action" not in reports[-1]
