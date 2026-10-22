"""Explicit numbered localhost load test; bounded, incremental PCAP inspection."""

import json
import shutil
import socket
import struct
import threading
import time
from itertools import islice
from pathlib import Path
from uuid import uuid4

from vil_logging.adapters.external import configure_worker_environment
from vil_logging.contracts.models import Role, SessionPhase
from vil_logging.diagnostics.connections import _find_tshark
from vil_logging.diagnostics.debug_log import DebugLogService
from vil_logging.monitors.rules import encode_rules
from vil_logging.runtime import Runtime

MAGIC = b"AutoLog!"


def validate_load(duration, pps, payload_size):
    if (any(type(value) is not int for value in (duration, pps, payload_size)) or
            not 1 <= duration <= 7200 or not 1 <= pps <= 100000 or not 64 <= payload_size <= 60000):
        raise ValueError("Duration 1–7200 s, rate 1–100000 packets/s, payload 64–60000 bytes required")
    if duration * pps > 10000000:
        raise ValueError("A single test is limited to 10,000,000 generated packets")


def inspect_sequences(path, token, expected, payload_size):
    """Keep one byte per expected sequence, never load the capture into memory."""
    seen = bytearray(expected)
    marker = MAGIC + token
    records = unique = duplicate = invalid = foreign = out_of_range = 0
    with Path(path).open("rb") as source:
        header = source.read(24)
        endian = {b"\xd4\xc3\xb2\xa1": "<", b"\xa1\xb2\xc3\xd4": ">",
                  b"\x4d\x3c\xb2\xa1": "<", b"\xa1\xb2\x3c\x4d": ">"}.get(header[:4])
        if len(header) != 24 or endian is None:
            raise ValueError("Expected a complete PCAP header")
        while record := source.read(16):
            if len(record) != 16:
                raise ValueError("Truncated PCAP record header")
            _, _, captured, original = struct.unpack(endian + "IIII", record)
            if captured > 262144 or captured > original:
                raise ValueError("Invalid or excessive packet length")
            packet = source.read(captured)
            if len(packet) != captured:
                raise ValueError("Truncated PCAP packet")
            records += 1
            offset = packet.find(marker)
            if offset < 0:
                foreign += 1
                continue
            payload = packet[offset:offset + payload_size]
            if len(payload) != payload_size or payload[len(marker) + 8:] != b"\xa5" * (payload_size - len(marker) - 8):
                invalid += 1
                continue
            number = struct.unpack_from("!Q", payload, len(marker))[0]
            if number >= expected:
                out_of_range += 1
            elif seen[number]:
                duplicate += 1
            else:
                seen[number] = 1
                unique += 1
    return {"records": records, "expected": expected, "unique": unique, "missing": expected - unique,
            "duplicates": duplicate, "invalid_payloads": invalid, "foreign_packets": foreign,
            "out_of_range": out_of_range,
            "missing_examples": list(islice((i for i, present in enumerate(seen) if not present), 20)),
            "passed": unique == expected and not (duplicate or invalid or foreign or out_of_range)}


def verify_load(data_dir, *, duration=10, pps=1000, payload_size=512, tshark_path=""):
    validate_load(duration, pps, payload_size)
    root = Path(data_dir)
    if root.exists():
        raise ValueError("Load verification requires a new folder")
    root.mkdir(parents=True)
    expected = duration * pps
    report = {"passed": False, "physical_nic_opened": False, "app_data": str(root),
              "scope": "Numbered generated localhost UDP only; not a vehicle NIC throughput guarantee",
              "requested": {"duration_seconds": duration, "pps": pps, "payload_bytes": payload_size,
                            "packets": expected, "buffer_mib": 64}}
    configure_worker_environment()
    debug = DebugLogService(root)
    runtime = None
    debug.enable()
    try:
        if shutil.disk_usage(root).free < expected * (payload_size + 128) * 1.2 + 1024 ** 3:
            raise ValueError("Insufficient free disk space for requested load fixture plus 1 GiB reserve")
        tool = _find_tshark(tshark_path)
        if tool["status"] != "ready":
            raise RuntimeError(tool["message_en"])
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            receiver.bind(("127.0.0.1", 0))
            receiver.settimeout(.2)
            port = receiver.getsockname()[1]
            done = threading.Event()

            def consume():
                while not done.is_set():
                    try:
                        receiver.recvfrom(65535)
                    except socket.timeout:
                        pass

            consumer = threading.Thread(target=consume, name="load-udp-drain", daemon=True)
            consumer.start()
            try:
                runtime = Runtime(root, _verification_filter=f"udp dst port {port}")
                runtime.initialize().result(10)
                runtime.save_preferences({"tshark_path": tool["path"], "nic_id": r"\Device\NPF_Loopback",
                                          "ethernet_format": "pcap", "ethernet_buffer_mib": "64",
                                          "monitor_rules_json": encode_rules([])}).result(10)
                runtime.toggle((Role.ETHERNET,)).result(30)
                if runtime.phase != SessionPhase.RECORDING:
                    raise RuntimeError("Capture did not start normally")
                token = uuid4().bytes
                marker = MAGIC + token
                padding = b"\xa5" * (payload_size - len(marker) - 8)
                sent, started, next_query = 0, time.monotonic(), time.monotonic() + 1
                samples = []
                while sent < expected:
                    now = time.monotonic()
                    due = min(expected, int((now - started) * pps) + 1, sent + 1000)
                    while sent < due:
                        sender.sendto(marker + struct.pack("!Q", sent) + padding, ("127.0.0.1", port))
                        sent += 1
                    if now >= next_query:
                        runtime._submit(runtime._query).result(10)
                        samples.append(dict(runtime._quality_report))
                        while not runtime.messages.empty():
                            runtime.messages.get_nowait()
                        if runtime.phase != SessionPhase.RECORDING:
                            raise RuntimeError("Capture stopped during load")
                        next_query = time.monotonic() + 1
                    time.sleep(min(.001, 1 / pps))
                sending_seconds = time.monotonic() - started
                report["generator"] = {"sent": sent, "elapsed_seconds": sending_seconds,
                                       "achieved_pps": sent / sending_seconds,
                                       "achieved_payload_mbps": sent * payload_size * 8 / sending_seconds / 1e6}
                # Drain decode backlog before normal stop; never mistake send completion for capture completion.
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    runtime._submit(runtime._query).result(10)
                    if runtime._quality_report.get("parsed_packets", 0) >= sent:
                        break
                    time.sleep(.1)
                runtime.toggle((Role.ETHERNET,)).result(110)
                report["quality"] = dict(runtime._quality_report)
                path = runtime._plan.files[0].final_path
                if runtime.phase != SessionPhase.COMPLETED or not path.is_file():
                    raise RuntimeError("Normal archive validation failed; working files preserved")
                report["path"] = str(path)
                report["sequences"] = inspect_sequences(path, token, sent, payload_size)
                report["samples"] = samples
                report["passed"] = (report["sequences"]["passed"] and
                                    report["quality"].get("packet_count") == sent and
                                    report["quality"].get("capture_loss", {}).get("status") != "loss_reported" and
                                    sending_seconds <= duration * 1.1)
                debug.log("verification.load_result", report=report)
            finally:
                done.set()
                consumer.join(2)
    except Exception as error:
        debug.exception("verification.load_failed", error)
        report["error"] = str(error)
    finally:
        if runtime:
            try:
                if not runtime.request_exit().result(120):
                    report["passed"] = False
                    report["exit_error"] = "Orderly exit was not confirmed"
            except Exception as error:
                report["passed"] = False
                report["exit_error"] = str(error)
            runtime.close_for_test()
        debug.close()
        (root / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
