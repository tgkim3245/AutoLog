import time
from copy import deepcopy
from pathlib import Path

import pytest

from vil_logging.contracts.commands import Command, CommandResult
from vil_logging.contracts.models import ObservationState, Role, SessionPhase
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
        self.report_age = 0

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
            success = not (action == "query" and role == self.query_error)
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


def test_monitor_criteria_persist_without_schema_change_or_invented_defaults(tmp_path):
    repo = Repository(tmp_path / "state.sqlite3")
    assert repo.load_settings().monitor_rules_json == ""
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


def test_source_episode_is_merged_and_warning_never_stops_capture(real):
    runtime, tools = real
    runtime.toggle((Role.ETHERNET,)).result(5)
    assert runtime._snapshots[Role.ETHERNET].observation == ObservationState.NORMAL
    tools.monitor = report("warning", source=1)
    for _ in range(12):
        runtime._submit(runtime._query).result(5)
    assert runtime.phase == SessionPhase.RECORDING
    assert runtime._snapshots[Role.ETHERNET].observation == ObservationState.WARNING
    assert len([event for event in events(runtime) if event.code == "MONITOR_SOURCE"]) == 1
    assert not any(action == "stop" for _, action, _ in tools.calls)
    tools.monitor = report("normal", source=1, recovered=1)
    runtime._submit(runtime._query).result(5)
    assert len([event for event in events(runtime) if event.code == "MONITOR_RECOVERED"]) == 1
    started = next(kwargs for _, action, kwargs in tools.calls if action == "start")
    assert started["params"]["monitor_rules_json"] == criteria()
    runtime.toggle((Role.ETHERNET,)).result(5)
    assert runtime._snapshots[Role.ETHERNET].observation == ObservationState.NOT_MONITORED
    capture = runtime._submit(runtime._repo.captures).result(5)[0]
    assert capture["details"]["monitoring"]["ethernet"]["rules"][0]["counters"]["source"] == 1


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
    assert runtime.phase == SessionPhase.PARTIAL
    assert runtime._snapshots[Role.CAN].recording.value == "recording"
    assert runtime._snapshots[Role.ETHERNET].observation == ObservationState.UNKNOWN
    assert not any(event.code == "MONITOR_MISSING" for event in events(runtime))


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
