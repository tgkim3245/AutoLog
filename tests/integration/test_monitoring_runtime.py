import time
from copy import deepcopy
from pathlib import Path

import pytest

from vil_logging.contracts.commands import Command, CommandResult
from vil_logging.contracts.models import ConnectionState, ObservationState, Role, SessionPhase
from vil_logging.monitors.rules import EthernetRule, encode_rules
from vil_logging.runtime import Runtime
from vil_logging.storage.repository import Repository


def criteria():
    return encode_rules([EthernetRule("rule", "Generated ECU", 1000, 0, 250, 2,
                                      destination_ip="192.0.2.100", expected_ip="192.0.2.1")])


def report(status="normal", *, source=0, recovered=0):
    return {"status": status, "sampled_epoch": time.time(), "rules": [{"id": "rule", "name": "Generated ECU", "status": status,
        "reasons": ["unexpected_source"] if status == "warning" else [],
        "counters": {"source": source, "missing": 0, "recovered": recovered, "unknown": 0},
        "max_delay_ms": 250, "matched_packets": 12, "mismatched_packets": source * 10,
        "last_capture_utc": "2026-10-18T00:00:00Z"}]}


class Tools:
    def __init__(self):
        self.calls = []
        self.paths = {}
        self.monitor = report()
        self.session_override = ""
        self.display_drops = 0
        self.query_error = None
        self.query_errors = set()
        self.query_details = {}
        self.query_states = {}
        self.report_age = 0
        self.quality = None
        self.stop_error = None

    def request(self, roles, action, session_id, **kwargs):
        self.calls.append((tuple(roles), action, kwargs))
        results = {}
        for role in roles:
            params = kwargs.get("role_params", {}).get(role, kwargs.get("params", {}))
            state = {"prepare": "ready", "configure": "configured", "start": "recording",
                     "query": "recording", "stop": "stopped", "inspect": "verified", "restore": "stopped"}[action]
            if action in {"configure", "start"}:
                self.paths[role] = Path(params["temp_path"])
                if action == "start":
                    self.paths[role].write_bytes(b"generated fixture")
            details = {}
            if action in {"start", "query", "stop"}:
                details = {"monitor": {**deepcopy(self.monitor), "session_id": self.session_override or session_id},
                           "summary_drops": self.display_drops, "parsed_packets": 15}
                details["monitor"]["sampled_epoch"] = time.time() - self.report_age
                if action == "stop":
                    details["monitor"]["status"] = "not_monitored"
            if action == "inspect":
                info = self.paths[role].stat()
                details = {"inode": info.st_ino, "bytes": info.st_size, "mtime_ns": info.st_mtime_ns,
                           "actual_format": "pcap", "packet_count": 1}
            if action == "query":
                details.update(deepcopy(self.query_details.get(role, {})))
                state = self.query_states.get(role, state)
            success = not ((action == "query" and (role == self.query_error or role in self.query_errors)) or
                           (action == "stop" and role == self.stop_error))
            if self.quality is not None and role == Role.ETHERNET:
                details.update(deepcopy(self.quality))
                details["session_id"] = self.session_override or session_id
            if not success:
                state = "error"
            results[role] = CommandResult(Command(action, role, session_id), success, state, "generated evidence", details=details)
        return results

    def close(self, **kwargs):
        pass

    def drain_packets(self):
        return []


@pytest.fixture
def real(tmp_path):
    runtime = Runtime(tmp_path)
    runtime.initialize().result(5)
    runtime._pool.close(abnormal=True)
    tools = Tools()
    runtime._pool = tools
    runtime.save_preferences({"monitor_rules_json": criteria(), "can_cfg": "C:/generated/can.cfg"}).result(5)
    yield runtime, tools
    runtime.close_for_test()


def events(runtime):
    return runtime._submit(runtime._repo.recent_events).result(5)


def test_changing_ethernet_connection_choices_invalidates_the_previous_check(real, monkeypatch):
    runtime, tools = real
    monkeypatch.setattr(runtime, "_begin_discovery", lambda: None)
    runtime._submit(runtime._target, Role.ETHERNET, connection=ConnectionState.READY).result(5)
    runtime.save_preferences({"nic_id": "changed-example-network"}).result(5)
    assert runtime._snapshots[Role.ETHERNET].connection == ConnectionState.UNKNOWN
    assert not tools.calls


def test_existing_profile_is_repaired_before_capture_and_not_repaired_again(tmp_path):
    from vil_logging.monitors.rules import DEFAULT_RULE_ID, parse_rules
    repository = Repository(tmp_path / "state.sqlite3")
    repository.load_settings(str(tmp_path))
    repository.save_preferences({"monitor_rules_json": encode_rules([
        EthernetRule("replacement", "zipy 활성화 검사", 1000, 1000, 1000, 10,
                     source_mac_prefix="02:00:00", popup_message="지피 확인하세요.")])})
    repository.close()
    runtime = Runtime(tmp_path)
    try:
        runtime.initialize().result(5)
        rules = parse_rules(runtime._settings.monitor_rules_json)
        assert len(rules) == 1 and rules[0].id == DEFAULT_RULE_ID
        assert rules[0].grace_ms == rules[0].timeout_ms == 2000
        runtime.save_preferences({"monitor_rules_json": encode_rules([])}).result(5)
    finally:
        runtime.close_for_test()
    runtime = Runtime(tmp_path)
    try:
        runtime.initialize().result(5)
        assert parse_rules(runtime._settings.monitor_rules_json) == ()
    finally:
        runtime.close_for_test()


def test_quality_warns_once_without_stopping_and_archives_evidence(real):
    runtime, tools = real
    tools.quality = {"performance": {"disk_free_bytes": 100, "sampled_epoch": time.time()},
                     "parsed_packets": 1, "summary_drops": 20,
                     "capture_loss": {"status": "loss_reported", "driver_dropped": 2, "os_dropped": None},
                     "summary_consistency": {"same_count": True}}
    runtime.save_preferences({"ethernet_buffer_mib": "128"}).result(5)
    runtime.toggle((Role.ETHERNET,)).result(5)
    for _ in range(3):
        runtime._submit(runtime._query).result(5)
    assert runtime.phase == SessionPhase.RECORDING
    assert sum(event.code == "DISK_SPACE_LOW" for event in events(runtime)) == 1
    assert runtime._quality_report["display_drops"] == 20
    prepared = next(kwargs for _, action, kwargs in tools.calls if action == "prepare")
    assert prepared["params"]["buffer_mib"] == "64"
    tools.quality["performance"]["disk_free_bytes"] = 2 * 1024 ** 3
    runtime._submit(runtime._query).result(5)
    assert sum(event.code == "DISK_SPACE_RESTORED" for event in events(runtime)) == 1
    runtime.toggle((Role.ETHERNET,)).result(5)
    assert runtime.phase == SessionPhase.COMPLETED
    assert runtime._quality_report["state"] == "archived"
    assert runtime._quality_report["capture_loss"]["driver_dropped"] == 2
    stored = runtime._submit(runtime._repo.captures).result(5)[0]
    assert stored["details"]["capture_quality"] == runtime._quality_report
    assert sum(event.code == "CAPTURE_DROP_REPORTED" for event in events(runtime)) == 1
    reopened = Runtime(runtime.data_dir)
    try:
        reopened.initialize().result(5)
        assert reopened._quality_report["state"] == "historical"
        assert reopened._quality_report["capture_loss"]["driver_dropped"] == 2
    finally:
        reopened.close_for_test()


def test_quality_rejects_old_session_and_failed_stop_never_looks_archived(real):
    runtime, tools = real
    tools.quality = {"performance": {"sampled_epoch": time.time()}, "parsed_packets": 1}
    runtime.toggle((Role.ETHERNET,)).result(5)
    tools.session_override = "previous-session"
    tools.quality["parsed_packets"] = 999
    runtime._submit(runtime._query).result(5)
    assert runtime._quality_report["parsed_packets"] == 1
    tools.stop_error = Role.ETHERNET
    runtime.toggle((Role.ETHERNET,)).result(5)
    assert runtime.phase == SessionPhase.INCOMPLETE
    assert runtime._quality_report["state"] == "unknown"
    assert runtime._plan.files[0].temp_path.is_file()


def test_monitor_criteria_persist_with_default_zipy_rule_without_schema_change(tmp_path):
    repo = Repository(tmp_path / "state.sqlite3")
    assert "02:00:00" in repo.load_settings().monitor_rules_json
    saved = repo.save_preferences({"monitor_rules_json": criteria()})
    repo.close()
    reopened = Repository(tmp_path / "state.sqlite3")
    try:
        assert reopened.load_settings() == saved
        assert reopened._connection.execute("PRAGMA user_version").fetchone()[0] == 2
        with pytest.raises(ValueError):
            reopened.save_preferences({"monitor_rules_json": "{}"})
        assert reopened.load_settings() == saved
    finally:
        reopened.close()


def test_receive_warning_stops_once_archives_and_allows_next_recording(real):
    runtime, tools = real
    runtime.toggle((Role.CAN, Role.ETHERNET)).result(5)
    tools.monitor = report("warning", source=1)
    for _ in range(3):
        runtime._submit(runtime._query).result(5)
    assert runtime.phase == SessionPhase.FAILED
    stops = [roles for roles, action, _ in tools.calls if action == "stop"]
    assert len(stops) == 1 and set(stops[0]) == {Role.CAN, Role.ETHERNET}
    runtime._submit(runtime._stop).result(5)
    assert len([action for _, action, _ in tools.calls if action == "stop"]) == 1
    assert len([event for event in events(runtime) if event.code == "CAPTURE_AUTO_STOP"]) == 1
    capture = runtime._submit(runtime._repo.captures).result(5)[0]
    assert capture["details"]["monitoring"]["ethernet"]["rules"][0]["counters"]["source"] == 1
    assert all(file.final_path.is_file() for file in runtime._plan.files)
    tools.monitor = report()
    runtime.toggle((Role.CAN, Role.ETHERNET)).result(5)
    assert runtime.phase == SessionPhase.RECORDING
    runtime.toggle((Role.CAN, Role.ETHERNET)).result(5)
    assert runtime.phase == SessionPhase.COMPLETED


def test_display_overflow_does_not_taint_independent_monitor(real):
    runtime, tools = real
    runtime.toggle((Role.ETHERNET,)).result(5)
    tools.display_drops = 1000
    for _ in range(3):
        runtime._submit(runtime._query).result(5)
    assert runtime._snapshots[Role.ETHERNET].observation == ObservationState.NORMAL
    assert len([event for event in events(runtime) if event.code == "DISPLAY_SUMMARY_LOSS"]) == 1
    assert not any(event.code == "OBSERVATION_LOSS" for event in events(runtime))


def test_observation_fault_and_stale_session_never_become_packet_loss(real):
    runtime, tools = real
    runtime.toggle((Role.ETHERNET,)).result(5)
    tools.session_override = "old-session"
    tools.monitor = report("warning", source=9)
    runtime._submit(runtime._query).result(5)
    assert runtime.phase == SessionPhase.RECORDING
    assert runtime._snapshots[Role.ETHERNET].observation == ObservationState.UNKNOWN
    assert not any(event.code == "MONITOR_SOURCE" for event in events(runtime))
    tools.session_override = ""
    tools.monitor = {"status": "unknown", "rules": [], "reasons": ["monitor_internal_error"], "error": "injected"}
    runtime._submit(runtime._query).result(5)
    assert runtime.phase == SessionPhase.RECORDING
    tools.monitor = report()
    runtime._submit(runtime._query).result(5)
    assert any(event.code == "MONITOR_OBSERVATION_RESTORED" for event in events(runtime))
    assert not any(event.code == "MONITOR_MISSING" for event in events(runtime))


def test_canoe_receive_unsupported_and_recorder_failure_remain_distinct(real):
    runtime, tools = real
    runtime.toggle((Role.CAN, Role.ETHERNET)).result(5)
    assert runtime._snapshots[Role.CAN].observation == ObservationState.UNSUPPORTED
    tools.query_error = Role.ETHERNET
    runtime._submit(runtime._query).result(5)
    assert runtime.phase == SessionPhase.FAILED
    assert runtime._snapshots[Role.CAN].recording.value == "stopped"
    assert runtime._snapshots[Role.ETHERNET].observation == ObservationState.NOT_MONITORED
    assert not any(event.code == "MONITOR_MISSING" for event in events(runtime))


def test_cable_unplug_stops_every_target_and_preserves_files_once(real):
    runtime, tools = real
    runtime.toggle((Role.CAN, Role.ETHERNET)).result(5)
    tools.quality = {"link": {"state": "disconnected"}}
    runtime._submit(runtime._query).result(5)
    assert runtime.phase == SessionPhase.FAILED
    assert all(file.final_path.is_file() for file in runtime._plan.files)
    stops = [roles for roles, action, _ in tools.calls if action == "stop"]
    assert len(stops) == 1 and set(stops[0]) == {Role.CAN, Role.ETHERNET}
    tools.quality = {"link": {"state": "connected"}}
    runtime.toggle((Role.CAN, Role.ETHERNET)).result(5)
    assert runtime.phase == SessionPhase.RECORDING
    runtime.toggle((Role.CAN, Role.ETHERNET)).result(5)
    assert runtime.phase == SessionPhase.COMPLETED


def test_recovered_receive_still_stops_when_worker_detected_a_failure_between_polls(real):
    runtime, tools = real
    runtime.toggle((Role.ETHERNET,)).result(5)
    tools.monitor["rules"][0]["violation_reasons"] = ["missing_flow"]
    runtime._submit(runtime._query).result(5)
    assert runtime.phase == SessionPhase.FAILED
    assert runtime._plan.files[0].final_path.is_file()


def test_validation_alert_carries_rule_message_once_while_normal_stop_archives(real):
    runtime, tools = real
    runtime.toggle((Role.ETHERNET,)).result(5)
    tools.monitor = report("warning", source=1)
    tools.monitor["rules"][0]["popup_message"] = "테스트 안내\n|6 → e1"
    runtime._submit(runtime._query).result(5)
    runtime._submit(runtime._query).result(5)
    alerts = []
    while not runtime.messages.empty():
        kind, value = runtime.messages.get_nowait()
        if kind == "validation_failure":
            alerts.append(value)
    assert len(alerts) == 1
    assert alerts[0]["rules"][0]["popup_message"] == "테스트 안내\n|6 → e1"
    assert runtime.phase == SessionPhase.FAILED
    assert runtime._plan.files[0].final_path.is_file()


def failure_alerts(runtime):
    alerts = []
    while not runtime.messages.empty():
        kind, value = runtime.messages.get_nowait()
        if kind in {"capture_failure", "validation_failure"}:
            alerts.append((kind, value))
    return alerts


@pytest.mark.parametrize("role,details,reason", [
    (Role.CAN, {"measurement_running": False}, "measurement_stopped"),
    (Role.DIAG, {"trigger_active": False}, "logging_stopped"),
    (Role.DIAG, {}, "recorder_unavailable"),
])
def test_canoe_failure_notifies_once_stops_all_and_allows_next_session(real, role, details, reason):
    runtime, tools = real
    runtime.save_preferences({"diag_cfg": "C:/generated/diag.cfg"}).result(5)
    roles = (Role.CAN, Role.DIAG, Role.ETHERNET)
    runtime.toggle(roles).result(5)
    if details:  # CANoe query can succeed while reporting that measurement/logging stopped.
        tools.query_states[role] = "error"
    else:
        tools.query_error = role
    tools.query_details[role] = details
    runtime._submit(runtime._query).result(5)
    runtime._submit(runtime._query).result(5)
    alerts = failure_alerts(runtime)
    assert len(alerts) == 1 and alerts[0][0] == "capture_failure"
    assert alerts[0][1]["targets"] == [{"role": role.value, "name": role.label, "reason": reason}]
    assert alerts[0][1]["rules"] == []  # No unrelated Zipy advice for a CANoe failure.
    assert runtime.phase == SessionPhase.FAILED
    assert all(file.final_path.is_file() for file in runtime._plan.files)
    stops = [selected for selected, action, _ in tools.calls if action == "stop"]
    assert len(stops) == 1 and set(stops[0]) == set(roles)
    assert sum(event.code == "CAPTURE_AUTO_STOP" for event in events(runtime)) == 1
    tools.query_error = None
    tools.query_details.clear()
    tools.query_states.clear()
    runtime.toggle(roles).result(5)
    assert runtime.phase == SessionPhase.RECORDING
    runtime.toggle(roles).result(5)
    assert runtime.phase == SessionPhase.COMPLETED


def test_simultaneous_can_diag_zipy_failures_have_one_combined_notification(real):
    runtime, tools = real
    runtime.save_preferences({"diag_cfg": "C:/generated/diag.cfg"}).result(5)
    runtime.toggle((Role.CAN, Role.DIAG, Role.ETHERNET)).result(5)
    tools.query_errors = {Role.CAN, Role.DIAG}
    tools.quality = {"link": {"state": "disconnected"}}
    tools.monitor = report("warning", source=1)
    tools.monitor["rules"][0]["popup_message"] = "Zipy custom advice"
    runtime._submit(runtime._query).result(5)
    alerts = failure_alerts(runtime)
    assert len(alerts) == 1 and alerts[0][0] == "capture_failure"
    assert {row["role"] for row in alerts[0][1]["targets"]} == {role.value for role in Role}
    assert alerts[0][1]["rules"][0]["popup_message"] == "Zipy custom advice"
    assert runtime.phase == SessionPhase.FAILED
    assert len([action for _, action, _ in tools.calls if action == "stop"]) == 1


def test_canoe_alert_is_published_even_when_normal_stop_cannot_finalize(real):
    runtime, tools = real
    runtime.toggle((Role.CAN, Role.ETHERNET)).result(5)
    tools.query_error = tools.stop_error = Role.CAN
    runtime._submit(runtime._query).result(5)
    assert runtime.phase == SessionPhase.INCOMPLETE
    assert len(failure_alerts(runtime)) == 1


def test_delayed_ipc_report_cannot_leave_a_stale_normal_status(real):
    runtime, tools = real
    runtime.toggle((Role.ETHERNET,)).result(5)
    tools.report_age = 10
    runtime._submit(runtime._query).result(5)
    target = runtime._snapshots[Role.ETHERNET]
    assert target.observation == ObservationState.UNKNOWN
    assert target.observation_details["rules"][0]["reasons"] == ["report_delayed"]
    assert runtime.phase == SessionPhase.RECORDING
    assert not any(event.code == "MONITOR_MISSING" for event in events(runtime))


def test_sustained_unavailable_receive_monitor_stops_instead_of_claiming_health(real):
    runtime, tools = real
    runtime.toggle((Role.ETHERNET,)).result(5)
    tools.monitor = {"status": "unknown", "rules": [], "reasons": ["reader_unavailable"]}
    runtime._monitor_unverified_since = time.monotonic() - 6
    runtime._submit(runtime._query).result(5)
    assert runtime.phase == SessionPhase.FAILED
    assert any(event.code == "CAPTURE_AUTO_STOP" for event in events(runtime))


def test_x_sends_canoe_exit_signal_before_busy_coordinator_finishes(real):
    import threading
    runtime, tools = real
    entered, release = threading.Event(), threading.Event()
    signals = []
    tools.signal_canoe_exit = lambda: signals.append("sent")
    tools.force_abort = lambda: None
    def busy():
        entered.set()
        release.wait(3)
    runtime._submit(busy)
    assert entered.wait(1)
    try:
        future = runtime.request_exit()
        assert signals == ["sent"] and not future.done()
    finally:
        release.set()
    assert future.result(5)


@pytest.mark.parametrize("document", ["", encode_rules([]), criteria()])
def test_upgrade_only_adds_zipy_default_to_legacy_blank_settings(tmp_path, document):
    first = Runtime(tmp_path)
    first.initialize().result(5)
    first.save_preferences({"monitor_rules_json": document, "nic_id": "remembered", "language": "en"}).result(5)
    first.close_for_test()
    second = Runtime(tmp_path)
    try:
        second.initialize().result(5)
        assert second._settings.nic_id == "remembered" and second._settings.language == "en"
        if document:
            assert second._settings.monitor_rules_json == document
        else:
            assert "02:00:00" in second._settings.monitor_rules_json
    finally:
        second.close_for_test()


@pytest.mark.parametrize("compression", ["none", "zip"])
def test_normal_stop_archives_selected_ethernet_storage_mode(real, compression):
    import zipfile
    runtime, tools = real
    runtime.save_preferences({"ethernet_compression": compression}).result(5)
    runtime.toggle((Role.ETHERNET,)).result(8)
    assert runtime.phase == SessionPhase.RECORDING
    plan = runtime._plan
    raw = plan.files[0].temp_path.read_bytes()
    runtime.toggle((Role.ETHERNET,)).result(8)
    assert runtime.phase == SessionPhase.COMPLETED
    file = plan.files[0]
    assert not file.temp_path.exists()
    if compression == "zip":
        with zipfile.ZipFile(file.final_path) as archive:
            assert archive.read(file.temp_path.name) == raw
    else:
        assert file.final_path.read_bytes() == raw
    history = runtime.refresh_file_history().result(5)
    assert history[0]["can_rename"]
    assert history[0]["files"][0]["path"] == str(file.final_path)


def test_zip_storage_failure_keeps_raw_and_reports_failed(real, monkeypatch):
    import zipfile
    runtime, tools = real
    runtime.save_preferences({"ethernet_compression": "zip"}).result(5)
    runtime.toggle((Role.ETHERNET,)).result(8)
    file = runtime._plan.files[0]
    raw = file.temp_path.read_bytes()
    def disk_full(*args, **kwargs):
        raise OSError("generated disk full")
    monkeypatch.setattr(zipfile.ZipFile, "open", disk_full)
    runtime.toggle((Role.ETHERNET,)).result(8)
    assert runtime.phase == SessionPhase.FAILED
    assert file.temp_path.read_bytes() == raw
    assert not file.final_path.exists()
    assert any(event.code == "FILE_ERROR" for event in events(runtime))
