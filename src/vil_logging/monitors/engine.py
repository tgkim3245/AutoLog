"""Bounded per-rule receive facts, evaluated before the display queue.

The capture adapter serializes calls with its statistics lock. All deadlines
use a monotonic clock; captured wall time detects delayed/backlogged input.
"""

import math
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class RuleState:
    rule: object
    baseline: float = 0
    last_flow: float | None = None
    last_capture_utc: str = ""
    last_source: str = ""
    last_source_mac: str = ""
    last_mismatch_utc: str = ""
    last_mismatch_source: str = ""
    last_mismatch_mac: str = ""
    source_started_utc: str = ""
    missing_started_utc: str = ""
    last_recovery_utc: str = ""
    missing: bool = False
    source_warning: bool = False
    good: int = 0
    matched: int = 0
    mismatches: int = 0
    lagged: bool = False
    uncertain_until: float = 0
    issue: str = ""
    clock_changed: bool = False
    previous_status: str = ""
    rate_buckets: deque = field(default_factory=lambda: deque(maxlen=21))
    low_rate_since: float | None = None
    violation_reasons: list = field(default_factory=list)
    violation_utc: str = ""
    counters: dict = field(default_factory=lambda: {"missing": 0, "source": 0, "recovered": 0, "unknown": 0})


class MonitorEngine:
    def __init__(self, rules=(), session_id="", *, monotonic=time.monotonic, wall=time.time):
        self._mono, self._wall = monotonic, wall
        self.rules = [RuleState(rule) for rule in rules]
        self.session_id = session_id
        self.active = False
        self.offset = 0

    def activate(self):
        self.active = True
        now = self._mono()
        self.offset = self._wall() - now
        for state in self.rules:
            state.baseline = now

    def stop(self):
        self.active = False

    def invalidate(self, reason):
        if not self.active:
            return
        now = self._mono()
        for state in self.rules:
            state.issue = reason
            state.uncertain_until = now + state.rule.timeout_ms / 1000
            state.baseline = now
            state.last_flow = None
            state.good = 0
            state.rate_buckets.clear()
            state.low_rate_since = None

    def _health(self, state, now, wall, reader_ok):
        if abs((wall - now) - self.offset) > state.rule.max_delay_ms / 1000:
            state.clock_changed = True
        if state.clock_changed:
            return "clock_changed"
        if not reader_ok:
            return "reader_unavailable"
        if state.lagged:
            return "capture_delayed"
        if now < state.uncertain_until:
            return state.issue or "observation_gap"
        return ""

    def _evaluate(self, state, now, wall, reader_ok):
        reason = self._health(state, now, wall, reader_ok)
        if reason:
            state.low_rate_since = None
            status, reasons = "unknown", [reason]
        else:
            age = now - (state.last_flow if state.last_flow is not None else state.baseline)
            expired = (now - state.baseline >= state.rule.grace_ms / 1000 and
                       age >= state.rule.timeout_ms / 1000)
            if expired and not state.missing:
                state.missing = True
                state.good = 0
                state.counters["missing"] += 1
                state.missing_started_utc = datetime.fromtimestamp(wall, UTC).isoformat(timespec="milliseconds")
            low_rate = (state.rule.minimum_pps and now - state.baseline >= max(2, state.rule.grace_ms / 1000)
                        and self._rate(state, now) < state.rule.minimum_pps)
            state.low_rate_since = (now if state.low_rate_since is None else state.low_rate_since) if low_rate else None
            rate_failed = state.low_rate_since is not None and now - state.low_rate_since >= state.rule.timeout_ms / 1000
            reasons = (["missing_flow"] if state.missing else []) + (["unexpected_source"] if state.source_warning else [])
            if rate_failed:
                reasons.append("low_receive_rate")
            if reasons and not state.violation_reasons:
                state.violation_reasons = list(reasons)
                state.violation_utc = datetime.fromtimestamp(wall, UTC).isoformat(timespec="milliseconds")
            status = "warning" if reasons else ("normal" if state.good >= state.rule.recovery_count else "unknown")
            if not reasons and status == "unknown":
                reasons = ["waiting_samples"]
        if status == "unknown" and state.previous_status != status:
            state.counters["unknown"] += 1
        state.previous_status = status
        return status, reasons

    @staticmethod
    def _rate(state, now):
        # Twenty completed 100 ms buckets; bounded memory even at very high PPS.
        bucket = int(now * 10)
        return sum(count for slot, count in state.rate_buckets if bucket - 20 <= slot < bucket) / 2

    def feed(self, packet):
        if not self.active or packet.session_id != self.session_id:
            return
        now, wall = self._mono(), self._wall()
        epoch = packet.captured_epoch
        for state in self.rules:
            # Detect backlog even in unrelated traffic: the expected flow may be behind it.
            if epoch is None or not math.isfinite(epoch) or abs(wall - epoch) > state.rule.max_delay_ms / 1000:
                state.lagged = True
                state.good = 0
                continue
            was_lagged = state.lagged
            state.lagged = False
            if was_lagged:
                state.baseline = now
                state.last_flow = None
                state.rate_buckets.clear()
                state.low_rate_since = None
            self._evaluate(state, now, wall, True)
            if self._health(state, now, wall, True) or not state.rule.in_flow(packet):
                continue
            state.last_flow = now
            state.last_capture_utc = packet.timestamp
            state.last_source, state.last_source_mac = packet.source, packet.source_mac
            state.matched += 1
            bucket = int(now * 10)
            if state.rate_buckets and state.rate_buckets[-1][0] == bucket:
                slot, count = state.rate_buckets.pop()
                state.rate_buckets.append((slot, count + 1))
            else:
                state.rate_buckets.append((bucket, 1))
            if not state.rule.expected_source(packet):
                state.good = 0
                state.mismatches += 1
                state.last_mismatch_utc = packet.timestamp
                state.last_mismatch_source, state.last_mismatch_mac = packet.source, packet.source_mac
                if not state.source_warning:
                    state.counters["source"] += 1
                    state.source_started_utc = packet.timestamp
                state.source_warning = True
                state.missing = False  # The selected flow is present, with an unexpected source.
            else:
                state.good += 1
                if state.good >= state.rule.recovery_count and (state.missing or state.source_warning):
                    state.missing = state.source_warning = False
                    state.counters["recovered"] += 1
                    state.last_recovery_utc = packet.timestamp

    def snapshot(self, *, reader_ok=True):
        now, wall = self._mono(), self._wall()
        rows = []
        for state in self.rules:
            status, reasons = self._evaluate(state, now, wall, reader_ok) if self.active else ("not_monitored", [])
            rows.append({"id": state.rule.id, "name": state.rule.name, "status": status, "reasons": reasons,
                         "last_capture_utc": state.last_capture_utc, "last_source": state.last_source,
                         "last_source_mac": state.last_source_mac, "last_mismatch_utc": state.last_mismatch_utc,
                         "last_mismatch_source": state.last_mismatch_source, "last_mismatch_mac": state.last_mismatch_mac,
                         "source_started_utc": state.source_started_utc, "missing_started_utc": state.missing_started_utc,
                         "last_recovery_utc": state.last_recovery_utc,
                         "age_ms": round((now - state.last_flow) * 1000) if state.last_flow is not None else None,
                         "matched_packets": state.matched, "mismatched_packets": state.mismatches,
                         "receive_pps": round(self._rate(state, now), 1), "minimum_pps": state.rule.minimum_pps,
                         "violation_reasons": list(state.violation_reasons), "violation_utc": state.violation_utc,
                         "max_delay_ms": state.rule.max_delay_ms,
                         "recovery_samples": min(state.good, state.rule.recovery_count),
                         "counters": dict(state.counters)})
        status = ("not_monitored" if not self.active else "not_configured" if not rows else
                  "unknown" if any(row["status"] == "unknown" for row in rows) else
                  "warning" if any(row["status"] == "warning" for row in rows) else "normal")
        return {"session_id": self.session_id, "status": status, "rules": rows,
                "sampled_epoch": wall, "scope": "parsed_metadata_before_display_queue"}
