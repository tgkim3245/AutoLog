"""Freshness of the report itself, including IPC and a stalled UI/coordinator."""

import math
import time


def fresh_report(report, *, now=None):
    if report.get("status") in {"not_monitored", "not_configured", "unsupported"}:
        return report
    now = time.time() if now is None else now
    sample = report.get("sampled_epoch")
    rows = report.get("rules", [])
    if not rows:
        return report if report.get("status") == "unknown" else {
            **report, "status": "unknown", "reasons": ["observation_unavailable"]}
    valid_sample = type(sample) in {int, float} and math.isfinite(sample)
    checked, changed = [], False
    for row in rows:
        delay = row.get("max_delay_ms")
        reason = ("observation_unavailable" if not valid_sample or type(delay) is not int or delay <= 0
                  else "report_delayed" if abs(now - sample) > delay / 1000 else "")
        if reason:
            row = {**row, "status": "unknown", "reasons": [reason],
                   "observed_status": row.get("observed_status", row["status"])}
            changed = True
        checked.append(row)
    return {**report, "status": "unknown", "rules": checked} if changed else report
