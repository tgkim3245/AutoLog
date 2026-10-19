import io
import json
import queue
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from vil_logging.adapters.tshark import TSharkCapture
from vil_logging.contracts.models import PacketSummary
from vil_logging.monitors.engine import MonitorEngine
from vil_logging.monitors.observation import fresh_report
from vil_logging.monitors.rules import EthernetRule, encode_rules, parse_rules


def rule(**patch):
    return replace(EthernetRule("one", "ECU", 1000, 2000, 250, 2,
                                destination_ip="192.0.2.100", expected_ip="192.0.2.1"), **patch)


class Clock:
    def __init__(self):
        self.now, self.epoch = 0.0, 1700000000.0

    def advance(self, seconds):
        self.now += seconds
        self.epoch += seconds

    def packet(self, source="192.0.2.1", destination="192.0.2.100", **patch):
        return replace(PacketSummary(datetime.fromtimestamp(self.epoch, UTC).isoformat(),
                                     source, destination, "UDP", 42, "02:00:00:00:00:01",
                                     "02:00:00:00:00:64", "session", source, destination, self.epoch), **patch)


def engine(clock, rules=None):
    monitor = MonitorEngine(rules or [rule()], "session", monotonic=lambda: clock.now, wall=lambda: clock.epoch)
    monitor.activate()
    return monitor


def row(monitor):
    return monitor.snapshot()["rules"][0]


def test_no_criteria_never_invents_normal_or_missing():
    clock = Clock()
    monitor = MonitorEngine(monotonic=lambda: clock.now, wall=lambda: clock.epoch)
    assert monitor.snapshot()["status"] == "not_monitored"
    monitor.activate()
    clock.advance(10000)
    assert monitor.snapshot()["status"] == "not_configured"
    monitor.stop()
    assert monitor.snapshot()["status"] == "not_monitored"


def test_real_receive_events_count_even_when_values_and_payload_are_unchanged():
    clock = Clock()
    monitor = engine(clock)
    monitor.feed(clock.packet())
    assert row(monitor)["status"] == "unknown"
    clock.advance(.1)
    monitor.feed(clock.packet())
    assert row(monitor)["status"] == "normal"
    assert row(monitor)["matched_packets"] == 2


def test_missing_respects_grace_and_requires_explicit_recovery_samples():
    clock = Clock()
    monitor = engine(clock)
    clock.advance(1.9)
    assert row(monitor)["status"] == "unknown"
    clock.advance(.2)
    assert row(monitor)["reasons"] == ["missing_flow"]
    assert row(monitor)["counters"]["missing"] == 1
    clock.advance(10)
    assert row(monitor)["counters"]["missing"] == 1
    monitor.feed(clock.packet())
    assert row(monitor)["status"] == "warning"
    clock.advance(.1)
    monitor.feed(clock.packet())
    assert row(monitor)["status"] == "normal"
    assert row(monitor)["counters"]["recovered"] == 1


def test_unrelated_traffic_neither_triggers_source_mismatch_nor_resets_flow_timeout():
    clock = Clock()
    monitor = engine(clock)
    for _ in range(30):
        clock.advance(.1)
        monitor.feed(clock.packet(source="198.51.100.9", destination="198.51.100.100"))
    evidence = row(monitor)
    assert evidence["matched_packets"] == evidence["mismatched_packets"] == 0
    assert evidence["reasons"] == ["missing_flow"]


def test_source_warning_is_merged_and_retained_even_if_recovered_between_queries():
    clock = Clock()
    monitor = engine(clock)
    for _ in range(50):
        monitor.feed(clock.packet(source="192.0.2.9"))
        clock.advance(.1)
    evidence = row(monitor)
    assert evidence["counters"]["source"] == 1 and evidence["mismatched_packets"] == 50
    assert evidence["counters"]["missing"] == 0
    assert evidence["last_mismatch_source"] == "192.0.2.9"
    monitor.feed(clock.packet())
    monitor.feed(clock.packet())
    evidence = row(monitor)
    assert evidence["status"] == "normal"
    assert evidence["counters"]["recovered"] == 1
    assert evidence["last_mismatch_source"] == "192.0.2.9"


@pytest.mark.parametrize("offset", [-10, 10, float("nan")])
def test_delayed_or_future_packets_suspend_assessment_instead_of_claiming_missing(offset):
    clock = Clock()
    monitor = engine(clock)
    monitor.feed(clock.packet(captured_epoch=clock.epoch + offset))
    clock.advance(10)
    evidence = row(monitor)
    assert evidence["status"] == "unknown" and evidence["reasons"] == ["capture_delayed"]
    assert evidence["counters"]["missing"] == 0
    monitor.feed(clock.packet())
    monitor.feed(clock.packet())
    assert row(monitor)["status"] == "normal"


def test_parse_gap_and_reader_failure_do_not_become_communication_loss():
    clock = Clock()
    monitor = engine(clock)
    clock.advance(3)
    monitor.invalidate("parse_error")
    assert row(monitor)["status"] == "unknown"
    assert row(monitor)["counters"]["missing"] == 0
    clock.advance(.5)
    assert monitor.snapshot(reader_ok=False)["rules"][0]["reasons"] == ["reader_unavailable"]
    clock.advance(2)
    assert monitor.snapshot(reader_ok=False)["rules"][0]["counters"]["missing"] == 0
    monitor.feed(clock.packet())
    monitor.feed(clock.packet())
    assert row(monitor)["status"] == "normal"


def test_wall_clock_changes_cannot_silently_restore_normal_timing():
    clock = Clock()
    monitor = engine(clock)
    clock.epoch += 60
    for _ in range(3):
        monitor.feed(clock.packet())
    assert row(monitor)["reasons"] == ["clock_changed"]
    clock.advance(10)
    assert row(monitor)["counters"]["missing"] == 0


def test_wrong_session_and_packets_after_stop_cannot_update_monitor():
    clock = Clock()
    monitor = engine(clock)
    monitor.feed(clock.packet(session_id="old-session"))
    assert row(monitor)["matched_packets"] == 0
    monitor.stop()
    monitor.feed(clock.packet())
    clock.advance(10)
    assert row(monitor)["status"] == "not_monitored"
    assert row(monitor)["matched_packets"] == 0


def test_multiple_rules_keep_independent_flow_facts():
    clock = Clock()
    monitor = engine(clock, [rule(), rule(id="two", destination_ip="192.0.2.200")])
    monitor.feed(clock.packet())
    monitor.feed(clock.packet())
    statuses = [item["status"] for item in monitor.snapshot()["rules"]]
    assert statuses == ["normal", "unknown"]
    assert monitor.snapshot()["status"] == "unknown"


@pytest.mark.parametrize("patch", [
    {"timeout_ms": 0}, {"timeout_ms": True}, {"grace_ms": -1}, {"max_delay_ms": 1001},
    {"recovery_count": 0}, {"expected_ip": "bad"}, {"destination_mac": "zz"},
    {"protocol": "UDP or TCP"}, {"destination_ip": ""}, {"name": ""},
])
def test_invalid_or_incomplete_rules_are_rejected(patch):
    with pytest.raises(ValueError):
        rule(**patch)


def test_rules_roundtrip_and_ipv6_mac_normalization():
    configured = rule(destination_ip="2001:0db8::1", expected_ip="2001:db8::2", expected_mac="02-00-00-00-00-AB")
    assert configured.destination_ip == "2001:db8::1"
    assert configured.expected_mac == "02:00:00:00:00:ab"
    assert parse_rules(encode_rules([configured])) == (configured,)
    assert parse_rules("") == ()
    with pytest.raises(ValueError):
        parse_rules(json.dumps({"version": 99, "ethernet": []}))
    with pytest.raises(ValueError):
        encode_rules([configured, configured])
    with pytest.raises(ValueError):
        parse_rules("{" + " " * 65536)


def test_display_queue_overflow_and_closed_packet_window_do_not_drop_monitor_input():
    clock = Clock()
    monitor = engine(clock, [rule(expected_ip="", destination_ip="", grace_ms=0, recovery_count=1)])
    capture = TSharkCapture(queue.Queue(maxsize=1))
    capture.session_id = "session"
    capture._monitor = monitor
    line = b"1700000000\t\t\t192.0.2.1\t\t192.0.2.100\t\tUDP\t42\n"
    capture.process = SimpleNamespace(stdout=io.BytesIO(line * 100))
    capture._observer = SimpleNamespace(process=capture.process)
    capture._consume_stdout()
    assert capture._parsed == 100 and capture._dropped == 99
    assert row(monitor)["matched_packets"] == 100
    assert row(monitor)["status"] == "normal"


def test_monitor_exception_never_interrupts_stdout_drain(monkeypatch):
    capture = TSharkCapture(queue.Queue(maxsize=1))
    capture.session_id = "session"
    line = b"1700000000\t\t\t192.0.2.1\t\t192.0.2.100\t\tUDP\t42\n"
    capture.process = SimpleNamespace(stdout=io.BytesIO(line * 100), pid=123, poll=lambda: None)
    capture._observer = SimpleNamespace(process=capture.process, errors=[], bytes_fed=0)

    def broken(*args):
        raise RuntimeError("injected monitor fault")

    monkeypatch.setattr(capture._monitor, "feed", broken)
    capture._consume_stdout()
    assert capture._parsed == 100 and capture._dropped == 99
    assert not capture._read_errors
    assert "injected monitor fault" in capture.stats()["monitor"]["error"]
    assert capture.stats()["monitor"]["status"] == "unknown"


def test_report_freshness_covers_transport_delay_without_rewriting_receive_facts():
    clock = Clock()
    monitor = engine(clock)
    monitor.feed(clock.packet())
    monitor.feed(clock.packet())
    report = monitor.snapshot()
    expired = fresh_report(report, now=clock.epoch + 1)
    assert expired["status"] == "unknown"
    assert expired["rules"][0]["observed_status"] == "normal"
    assert expired["rules"][0]["matched_packets"] == 2
    assert report["status"] == "normal"  # No mutation of the worker's evidence.
    assert fresh_report(expired, now=clock.epoch + 1) == expired


def test_non_ip_mac_flow_and_protocol_selector_are_independent_of_source():
    clock = Clock()
    configured = rule(destination_ip="", expected_ip="", protocol="ARP",
                      destination_mac="ff:ff:ff:ff:ff:ff", expected_mac="02:00:00:00:00:01")
    monitor = engine(clock, [configured])
    packet = clock.packet(source_ip="", destination_ip="", protocol="ARP",
                          destination_mac="ff:ff:ff:ff:ff:ff")
    monitor.feed(replace(packet, protocol="UDP"))
    assert row(monitor)["matched_packets"] == 0
    monitor.feed(packet)
    monitor.feed(packet)
    assert row(monitor)["status"] == "normal"
