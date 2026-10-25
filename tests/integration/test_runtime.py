"""Critical control policies with owned simulator processes and temporary SQLite."""

import threading
import time
from dataclasses import replace

import pytest

from vil_logging.contracts.commands import FakeBehavior
from vil_logging.contracts.models import Role, SessionPhase
from vil_logging.diagnostics.debug_log import DebugLogService
from vil_logging.runtime import Runtime
from vil_logging.storage.naming import build_plan
from vil_logging.storage.repository import Repository


@pytest.fixture
def runtime_factory(tmp_path):
    runtimes = []

    def create(*, demo=True, behaviors=None):
        runtime = Runtime(tmp_path / str(len(runtimes)), demo=demo, behaviors=behaviors)
        runtimes.append(runtime)
        runtime.initialize().result(timeout=8)
        return runtime

    yield create
    for runtime in runtimes:
        runtime.close_for_test()


def read_next(runtime):
    return runtime._submit(lambda: runtime._repo.load_settings().next_index).result(timeout=5)


def test_full_recent_history_cannot_drop_startup_recovery_or_exit(tmp_path):
    from vil_logging.contracts.models import AppEvent
    repo = Repository(tmp_path / "state.sqlite3")
    output = tmp_path / "captures"
    output.mkdir()
    settings = repo.load_settings(str(output))
    plan = build_plan(settings, (Role.CAN,))
    repo.reserve(plan)
    repo.update_session(plan.session_id, SessionPhase.INCOMPLETE,
                        capture_quality={"state": "unknown"})
    # An interrupted file operation adds another startup notification.
    repo.begin_file_operation("interrupted", "delete", {"items": []})
    for number in range(500):
        repo.append_event(AppEvent("OPERATION_ERROR", original=f"history-{number}"))
    repo.close()
    runtime = Runtime(tmp_path)
    try:
        runtime.initialize().result(5)
        # Startup is complete before the GUI begins draining messages.
        assert runtime._notification_loss == 0
        messages = list(runtime.messages.queue)
        assert {"settings", "phase", "recovery", "capture_quality"} <= {kind for kind, _ in messages}
        history = [value for kind, value in messages if kind == "events"]
        assert len(history) == 1 and len(history[0]) == 500
    finally:
        runtime.close_for_test()


def test_real_mode_cannot_claim_or_start_unvalidated_capture(runtime_factory):
    runtime = runtime_factory(demo=False)
    runtime.toggle((Role.CAN, Role.ETHERNET)).result(timeout=5)
    assert runtime.phase == SessionPhase.FAILED
    assert read_next(runtime) == 1
    assert runtime._plan is None
    assert not list(runtime.data_dir.rglob("*.blf"))


def test_startup_retention_notice_is_delivered_once_after_history(tmp_path):
    from vil_logging.contracts.models import AppEvent
    repo = Repository(tmp_path / "state.sqlite3")
    repo.load_settings()
    for _ in range(600):
        repo.append_event(AppEvent("OLD", timestamp="2020-01-01T00:00:00.000+00:00"))
    repo.close()
    runtime = Runtime(tmp_path, demo=True)
    try:
        runtime.initialize().result(8)
        events = []
        for kind, value in list(runtime.messages.queue):
            if kind == "events":
                events.extend(value)
            elif kind == "event":
                events.append(value)
        assert sum(event.code == "HISTORY_ARCHIVED" for event in events) == 1
        assert [event.code for event in events][500] == "HISTORY_ARCHIVED"
        assert runtime._notification_loss == 0
    finally:
        runtime.close_for_test()


def test_failed_ethernet_preparation_without_any_recorder_can_exit(runtime_factory):
    runtime = runtime_factory(demo=False)
    runtime.save_preferences({"tshark_path": "C:/AutoLog-missing-tool/tshark.exe"}).result(5)
    runtime.toggle((Role.ETHERNET,)).result(10)
    assert runtime.phase == SessionPhase.FAILED
    assert runtime._plan is None and read_next(runtime) == 1
    assert runtime.request_exit().result(5) is True


def test_empty_selection_does_not_consume_number(runtime_factory):
    runtime = runtime_factory()
    runtime.toggle(()).result(timeout=5)
    assert runtime.phase == SessionPhase.IDLE
    assert read_next(runtime) == 1


@pytest.mark.parametrize("language", ["ko", "en", "zh"])
def test_demo_start_stop_reserves_number_once_and_never_creates_captures(runtime_factory, language):
    runtime = runtime_factory()
    runtime.save_preferences({"language": language}).result(timeout=3)
    roles = tuple(Role)
    runtime.toggle(roles).result(timeout=12)
    assert runtime.phase == SessionPhase.RECORDING
    assert read_next(runtime) == 2
    runtime.toggle(roles).result(timeout=8)
    assert runtime.phase == SessionPhase.COMPLETED
    assert read_next(runtime) == 2
    assert not list(runtime.data_dir.rglob("*.blf"))
    assert not list(runtime.data_dir.rglob("*.pcap*"))
    assert runtime._submit(runtime._repo.recover_incomplete).result(timeout=5) == []


def test_initial_start_failure_stops_only_issued_targets_and_keeps_number(runtime_factory):
    runtime = runtime_factory(behaviors={Role.CAN: FakeBehavior(fail_start=True)})
    runtime.toggle((Role.CAN, Role.ETHERNET)).result(timeout=12)
    assert runtime.phase == SessionPhase.FAILED
    assert read_next(runtime) == 2
    results = runtime._submit(runtime._pool.request, (Role.ETHERNET,), "query", runtime._plan.session_id).result(timeout=5)
    assert results[Role.ETHERNET].state == "stopped"
    assert Role.DIAG not in runtime._pool._processes


def test_recording_failure_stops_healthy_target_too(runtime_factory):
    runtime = runtime_factory(behaviors={Role.CAN: FakeBehavior(fail_after=0.15)})
    roles = (Role.CAN, Role.ETHERNET)
    runtime.toggle(roles).result(timeout=12)
    time.sleep(0.25)
    runtime._submit(runtime._query).result(timeout=5)
    assert runtime.phase == SessionPhase.FAILED  # Past failure cannot become whole-session success.
    assert runtime._snapshots[Role.CAN].recording.value == "error"
    assert "Previous error:" in runtime._snapshots[Role.CAN].evidence
    assert runtime._snapshots[Role.ETHERNET].recording.value == "stopped"


def test_stop_unknown_blocks_new_session_until_x_discards_it(runtime_factory):
    runtime = runtime_factory(behaviors={Role.ETHERNET: FakeBehavior(fail_stop=True)})
    roles = (Role.ETHERNET,)
    runtime.toggle(roles).result(timeout=10)
    runtime.toggle(roles).result(timeout=8)
    assert runtime.phase == SessionPhase.INCOMPLETE
    assert runtime.toggle(roles) is None
    assert read_next(runtime) == 2
    assert runtime.request_exit().result(timeout=5) is True
    assert runtime.phase == SessionPhase.FAILED and runtime._closed


def test_cancel_while_final_db_commit_pending_never_leaves_recording(runtime_factory, monkeypatch):
    runtime = runtime_factory()
    entered, release = threading.Event(), threading.Event()
    original_update = runtime._repo.update_session

    def delayed_update(session_id, phase, **details):
        if phase == SessionPhase.RECORDING:
            entered.set()
            assert release.wait(timeout=5)
        return original_update(session_id, phase, **details)

    monkeypatch.setattr(runtime._repo, "update_session", delayed_update)
    future = runtime.toggle((Role.ETHERNET,))
    assert entered.wait(timeout=10)
    assert runtime.toggle((Role.ETHERNET,)) is None
    release.set()
    future.result(timeout=8)
    assert runtime.phase == SessionPhase.FAILED
    assert runtime._snapshots[Role.ETHERNET].recording.value == "stopped"
    assert read_next(runtime) == 2


def test_database_reservation_failure_sends_no_start(runtime_factory, monkeypatch):
    runtime = runtime_factory()
    calls = []
    original_request = runtime._pool.request

    def observe(roles, action, session_id, **kwargs):
        calls.append(action)
        return original_request(roles, action, session_id, **kwargs)

    def reject(_plan):
        raise OSError("injected storage failure")

    monkeypatch.setattr(runtime._pool, "request", observe)
    monkeypatch.setattr(runtime._repo, "reserve", reject)
    runtime.toggle((Role.ETHERNET,)).result(timeout=10)
    assert "start" not in calls
    assert read_next(runtime) == 1
    assert runtime.phase == SessionPhase.FAILED


def test_debug_file_contains_correlated_command_results_and_errors(runtime_factory, tmp_path):
    runtime = runtime_factory(behaviors={Role.CAN: FakeBehavior(crash_on_start=True)})
    service = DebugLogService(tmp_path / "debug")
    path = service.enable()
    try:
        runtime.toggle((Role.CAN, Role.ETHERNET)).result(timeout=12)
    finally:
        service.close()
    text = path.read_text(encoding="utf-8")
    assert "command_id" in text and "session_id" in text
    assert "injected demo worker exception" in text
    assert "Traceback" in text
    assert runtime.phase == SessionPhase.INCOMPLETE


def wait_for_message(runtime, kind, predicate=lambda value: True, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = max(0.01, deadline - time.monotonic())
        found, value = runtime.messages.get(timeout=remaining)
        if found == kind and predicate(value):
            return value
    raise AssertionError(f"No {kind} notification")


def test_missing_cfg_prepare_always_produces_progress_and_actionable_result(runtime_factory):
    runtime = runtime_factory(demo=False)
    runtime.prepare(Role.CAN).result(timeout=5)
    progress = wait_for_message(runtime, "preparation")
    assert progress["status"] == "checking"
    result = wait_for_message(runtime, "preparation", lambda item: item["status"] != "checking")
    assert result["status"] == "attention"
    assert ".cfg" in result["message_ko"]
    assert runtime._snapshots[Role.CAN].connection.value == "unknown"
    assert read_next(runtime) == 1


def test_slow_discovery_does_not_delay_stop(runtime_factory, monkeypatch):
    from vil_logging.diagnostics import connections
    runtime = runtime_factory()
    runtime.toggle((Role.ETHERNET,)).result(timeout=10)
    entered, release = threading.Event(), threading.Event()

    def slow_discovery(*_args):
        entered.set()
        assert release.wait(timeout=8)
        return {"tshark": {"status": "missing"}, "interfaces": []}

    monkeypatch.setattr(connections, "discover_connections", slow_discovery)
    try:
        runtime.discover().result(timeout=2)
        assert entered.wait(timeout=2)
        runtime.toggle((Role.ETHERNET,)).result(timeout=3)
        assert runtime.phase == SessionPhase.COMPLETED
    finally:
        release.set()


def test_late_preparation_result_does_not_validate_a_different_cfg(runtime_factory, monkeypatch):
    runtime = runtime_factory(demo=False)
    entered, release = threading.Event(), threading.Event()

    def slow_prepare(role, settings):
        entered.set()
        assert release.wait(timeout=8)
        return runtime._preparation_report(role, "ready", "Old result", "Old result"), None

    monkeypatch.setattr(runtime, "_check_connection", slow_prepare)
    try:
        runtime.prepare(Role.CAN).result(timeout=2)
        assert entered.wait(timeout=2)
        runtime.save_preferences({"can_cfg": "D:/another.cfg"}).result(timeout=2)
        release.set()
        result = wait_for_message(runtime, "preparation", lambda item: item["status"] != "checking")
        assert result["status"] == "attention"
        assert "변경" in result["message_ko"]
        assert runtime._snapshots[Role.CAN].connection.value == "unknown"
    finally:
        release.set()


def test_naming_apply_merges_with_latest_saved_paths(runtime_factory):
    runtime = runtime_factory()
    draft = replace(runtime._settings, prefix="new_", next_index=15)
    runtime.save_preferences({"can_cfg": "D:/recent.cfg"}).result(timeout=3)
    runtime.apply_naming(draft, (Role.CAN,)).result(timeout=3)
    assert runtime._settings.can_cfg == "D:/recent.cfg"
    assert runtime._settings.next_index == 15
    assert runtime._settings.prefix == "new_"


def test_inventory_refresh_never_replaces_the_user_selected_tool(runtime_factory, monkeypatch):
    from vil_logging.diagnostics import connections
    runtime = runtime_factory(demo=False)
    calls = []

    def discovery(path, nic):
        calls.append(path)
        return {"tshark": {"status": "ready", "path": "C:/found/tshark.exe"}, "interfaces": []}

    monkeypatch.setattr(connections, "discover_connections", discovery)
    runtime.save_preferences({"tshark_path": "C:/missing.exe"}).result(timeout=3)
    wait_for_message(runtime, "connections")
    assert runtime._settings.tshark_path == "C:/missing.exe"
    runtime.discover().result(timeout=3)
    wait_for_message(runtime, "connections")
    assert calls == ["C:/missing.exe", "C:/missing.exe"]
    assert runtime._settings.tshark_path == "C:/missing.exe"
    assert runtime._submit(runtime._repo.load_settings).result(timeout=3) == runtime._settings


def test_missing_npcap_is_reported_before_asking_for_a_network(runtime_factory, monkeypatch):
    from vil_logging.diagnostics import connections
    runtime = runtime_factory(demo=False)
    report = {"tshark": {"status": "ready", "path": "C:/tools/tshark.exe"},
              "npcap": {"status": "missing"}, "interfaces": [{"id": "nic", "name": "Ethernet",
              "capture_available": False}], "interface_query_error": "Unable to load Npcap (wpcap.dll)"}
    monkeypatch.setattr(connections, "discover_connections", lambda *_: report)
    runtime.prepare(Role.ETHERNET).result(timeout=3)
    result = wait_for_message(runtime, "preparation", lambda value: value["status"] != "checking")
    assert result["status"] == "attention"
    assert "TShark는 정상" in result["message_ko"]
    assert "Npcap" in result["message_ko"]
    assert "Initial_Setup.bat" in result["next_action_ko"]
    assert "종료" in result["next_action_ko"] and "네트워크" in result["next_action_ko"]
    assert "wpcap.dll" in result["detail"]
    event = wait_for_message(runtime, "event", lambda value: value.code == "TARGET_ATTENTION")
    assert event.level == "INFO"
    assert runtime._connections["interfaces"][0]["name"] == "Ethernet"


def test_canoe_measurement_waiting_reports_license_workflow_and_history_in_three_languages(runtime_factory, monkeypatch):
    from types import SimpleNamespace

    runtime = runtime_factory(demo=False)
    details = {"selected_block": "1", "measurement_running": False, "trigger_active": False,
               "hardware": {"status": "unavailable", "reference_required": False},
               "measurement_diagnostics": {"missing_options": ["Ethernet"], "current_license_verified": False}}
    result = SimpleNamespace(success=True, details=details)
    monkeypatch.setattr(runtime, "_request_real", lambda *_args, **_kwargs: {Role.CAN: result})
    runtime._submit(runtime._prepare_canoe, Role.CAN).result(timeout=3)
    report = wait_for_message(runtime, "preparation")
    assert report["status"] == "attention" and report["readiness_stage"] == "measurement_waiting"
    for language in ("ko", "en", "zh"):
        assert "F9" in report[f"message_{language}"]
        assert "Trace" in report[f"message_{language}"]
        assert "Ethernet" in report[f"detail_{language}"]
    assert runtime._settings.can_logging_block == "1"
    assert read_next(runtime) == 1
    assert runtime._plan is None


@pytest.mark.parametrize("issue", ["com_registration_missing", "com_registration_invalid"])
def test_canoe_registration_failure_explains_repair_in_all_languages(runtime_factory, monkeypatch, issue):
    from types import SimpleNamespace

    runtime = runtime_factory(demo=False)
    diagnostics = {"registry_key": "CANoe.Application/CLSID", "registry_modified": False,
                   "repair_tools": [{"registration_tool": "C:/Installed CANoe/Exec64/RegisterComponents.exe"}]}
    result = SimpleNamespace(success=False, evidence="Generated COM registration traceback",
                             details={"connection_issue": issue, "registration_diagnostics": diagnostics})
    monkeypatch.setattr(runtime, "_request_real", lambda *_args, **_kwargs: {Role.CAN: result})
    runtime._submit(runtime._prepare_canoe, Role.CAN).result(timeout=3)
    report = wait_for_message(runtime, "preparation")
    assert report["status"] == "error" and report["connection_issue"] == issue
    assert report["diagnostic_detail"] == result.evidence
    assert report["registration_diagnostics"] == diagnostics
    for language in ("ko", "en", "zh"):
        assert "COM" in report[f"message_{language}"]
        assert "Exec64" in report[f"detail_{language}"]
        assert diagnostics["repair_tools"][0]["registration_tool"] in report[f"detail_{language}"]
        assert report[f"next_action_{language}"]
    assert "설정 파일:" not in report["detail_ko"]
    assert runtime._plan is None and read_next(runtime) == 1
