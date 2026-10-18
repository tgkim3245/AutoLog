"""Read optional cumulative interface counters, skipping frame bodies.

This is supplemental evidence after capinfos validation, not a packet validator
or proof of lossless acquisition. Missing counters are always unknown.
"""

import struct
import time
from pathlib import Path


def capture_loss_report(path: Path, file_format: str, *, timeout=15) -> dict:
    unknown = {"status": "unknown", "driver_dropped": None, "os_dropped": None,
               "scope": "optional_pcapng_interface_statistics", "interfaces": []}
    if file_format != "pcapng":
        return {**unknown, "reason": "format_has_no_statistics"}
    try:
        return _read_statistics(Path(path), timeout)
    except (OSError, ValueError, struct.error) as error:
        return {**unknown, "reason": "statistics_unavailable", "error": str(error)}


def _read_statistics(path, timeout):
    before = path.stat()
    deadline = time.monotonic() + timeout
    interfaces, current = [], []
    order, section, position = None, -1, 0
    with path.open("rb") as source:
        while position < before.st_size:
            if time.monotonic() > deadline:
                raise ValueError("Interface statistics inspection timed out")
            source.seek(position)
            prefix = source.read(12)
            if len(prefix) != 12:
                raise ValueError("Truncated pcapng block")
            section_header = prefix[:4] == b"\x0a\x0d\x0d\x0a"
            if section_header:
                if prefix[8:12] not in {b"\x4d\x3c\x2b\x1a", b"\x1a\x2b\x3c\x4d"}:
                    raise ValueError("Invalid pcapng byte order")
                order = "<" if prefix[8:12] == b"\x4d\x3c\x2b\x1a" else ">"
                section += 1
                current = []
            if order is None:
                raise ValueError("Missing pcapng section header")
            kind, length = struct.unpack_from(order + "II", prefix)
            if length < (28 if section_header else 12) or length % 4 or position + length > before.st_size:
                raise ValueError("Invalid pcapng block length")
            source.seek(position + length - 4)
            if struct.unpack(order + "I", source.read(4))[0] != length:
                raise ValueError("Pcapng block lengths disagree")
            if kind == 1:
                if length < 20 or len(interfaces) >= 4096:
                    raise ValueError("Invalid or excessive interface metadata")
                item = {"section": section, "interface": len(current), "driver_dropped": None,
                        "os_dropped": None, "stats_entries": 0, "observed_drop": False,
                        "last_timestamp": -1}
                current.append(item)
                interfaces.append(item)
            elif kind == 5:
                if length < 24:
                    raise ValueError("Truncated interface statistics")
                source.seek(position + 8)
                identifier, high, low = struct.unpack(order + "III", source.read(12))
                if identifier >= len(current):
                    raise ValueError("Statistics refer to an unknown interface")
                item = current[identifier]
                stamp = (high << 32) | low
                if stamp < item["last_timestamp"]:
                    raise ValueError("Statistics timestamps are out of order")
                values, cursor, end = {}, position + 20, position + length - 4
                while cursor < end:
                    if time.monotonic() > deadline:
                        raise ValueError("Interface statistics inspection timed out")
                    source.seek(cursor)
                    if end - cursor < 4:
                        raise ValueError("Truncated statistics option")
                    code, size = struct.unpack(order + "HH", source.read(4))
                    cursor += 4
                    if code == 0:
                        if size:
                            raise ValueError("Invalid statistics end option")
                        break
                    padded = (size + 3) & ~3
                    if cursor + padded > end:
                        raise ValueError("Statistics option overruns its block")
                    if code in {5, 7}:
                        if size != 8 or code in values:
                            raise ValueError("Invalid or duplicate drop counter")
                        values[code] = struct.unpack(order + "Q", source.read(8))[0]
                    cursor += padded
                for key, code in (("driver_dropped", 5), ("os_dropped", 7)):
                    value = values.get(code)
                    previous = item[key]
                    if value is not None and previous is not None and value < previous:
                        raise ValueError("Cumulative drop counter decreased")
                    item[key] = value
                    item["observed_drop"] |= value is not None and value > 0
                item["stats_entries"] += 1
                item["last_timestamp"] = stamp
            position += length
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError("Capture changed during statistics inspection")
    totals = {key: sum(item[key] for item in interfaces) if interfaces and
              all(item[key] is not None for item in interfaces) else None
              for key in ("driver_dropped", "os_dropped")}
    status = ("loss_reported" if any(item["observed_drop"] for item in interfaces) else
              "reported" if any(value is not None for value in totals.values()) else "unknown")
    return {"status": status, **totals, "interfaces": interfaces,
            "reason": "interface_counters" if status != "unknown" else "missing_counters",
            "scope": "optional_pcapng_interface_statistics"}
