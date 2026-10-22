"""Explicit, opt-in localhost verification; never opens a physical adapter."""

import json
import socket
import struct
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from vil_logging.adapters.external import configure_worker_environment, external_environment
from vil_logging.adapters.tshark import FIELDS, parse_summary
from vil_logging.contracts.models import Role, SessionPhase
from vil_logging.diagnostics.connections import _find_tshark
from vil_logging.diagnostics.debug_log import DebugLogService
from vil_logging.monitors.rules import EthernetRule, encode_rules
from vil_logging.runtime import Runtime
from vil_logging.storage.blf import FILE_HEADER
from vil_logging.storage.file_access import observe
from vil_logging.storage.file_service import FileService
from vil_logging.storage.naming import build_plan
from vil_logging.storage.recovery import RecoveryService
from vil_logging.storage.repository import Repository


def verify_file_management(data_dir: Path) -> dict:
    """No adapter is opened. Only files created inside this new profile are used."""
    root = Path(data_dir)
    if root.exists():
        raise ValueError("Verification requires a new folder; existing profiles are preserved")
    root.mkdir(parents=True)
    output = root / "captures"
    output.mkdir()
    debug = DebugLogService(root)
    debug.enable()
    repository = None
    report = {"passed": False, "app_data": str(root), "physical_nic_opened": False,
              "scope": "Generated PCAP fixture and native Windows file operations only", "cases": []}
    try:
        repository = Repository(root / "state.sqlite3")
        settings = repository.load_settings(str(output))
        plan = build_plan(settings, (Role.ETHERNET,))
        repository.reserve(plan)
        file = plan.files[0]
        frame = bytes.fromhex("ffffffffffff0200000000010806" "0001080006040001"
                              "020000000001c0000201000000000000c0000202")
        file.final_path.write_bytes(struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1) +
                                    struct.pack("<IIII", 1, 0, len(frame), len(frame)) + frame)
        repository.update_capture_file(plan.session_id, Role.ETHERNET, "published",
                                       actual_path=str(file.final_path), inspection=observe(file.final_path))
        repository.update_session(plan.session_id, SessionPhase.COMPLETED, generated_verification_fixture=True)
        service = FileService(repository)
        result = service.rename_previous(plan.session_id, "renamed")
        if result["status"] != "completed":
            raise AssertionError(result)
        report["cases"].append({"case": "native_rename", "passed": True})
        repository.close()
        repository = Repository(root / "state.sqlite3")
        service = FileService(repository)
        selection = service.history()[0]["files"]
        path = Path(selection[0]["path"])
        if path.name != "renamed.pcap" or repository.load_settings().next_index != 2:
            raise AssertionError("Restart did not preserve the actual path and next index")
        report["cases"].append({"case": "restart_paths", "passed": True, "path": str(path)})
        with path.open("rb"):
            result = service.delete_selected(selection)
        if result["status"] != "blocked" or not path.is_file():
            raise AssertionError("An externally opened capture was not preserved")
        report["cases"].append({"case": "used_file_preserved", "passed": True})
        result = service.delete_selected(selection)
        if result["status"] != "completed" or path.exists():
            raise AssertionError("Native deletion did not complete")
        report["cases"].append({"case": "native_delete", "passed": True})
        repository.close()
        repository = Repository(root / "state.sqlite3")
        if (FileService(repository).history()[0]["files"][0]["status"] != "deleted"
                or repository.load_settings().next_index != 2):
            raise AssertionError("Deletion result or next index was not persisted")
        report["cases"].append({"case": "restart_deleted_metadata", "passed": True})
        report.update(passed=True, next_index=2, file_operations=len(repository.file_operations()))
    except Exception as error:
        debug.exception("verification.files_failed", error)
        report["error"] = str(error)
    finally:
        if repository:
            repository.close()
        debug.close()
        (root / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def verify_recovery(data_dir: Path, *, tshark_path: str = "") -> dict:
    """Exercise the packaged recovery path without opening a CANoe window or NIC."""
    root = Path(data_dir)
    if root.exists():
        raise ValueError("Verification requires a new folder; existing profiles are preserved")
    root.mkdir(parents=True)
    output = root / "captures"
    output.mkdir()
    debug = DebugLogService(root)
    debug.enable()
    repository = None
    report = {"passed": False, "app_data": str(root), "physical_nic_opened": False,
              "canoe_opened": False, "scope": "Generated offline capture recovery only", "cases": []}
    try:
        tool = _find_tshark(tshark_path)
        if tool["status"] != "ready":
            raise RuntimeError(tool["message_en"])
        fixtures = {
            "blf": FILE_HEADER.pack(b"LOGG", 144, *([0] * 8), 144, 144, 0, 0, *([0] * 16)).ljust(144, b"\0"),
            "pcap": struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1),
            "pcapng": (struct.pack("<IIIHHqI", 0x0A0D0D0A, 28, 0x1A2B3C4D, 1, 0, -1, 28) +
                       struct.pack("<IIHHII", 1, 20, 1, 0, 65535, 20)),
        }
        repository = Repository(root / "state.sqlite3")
        repository.load_settings(str(output))
        for extension, content in fixtures.items():
            repository.save_preferences({"ethernet_format": extension if extension != "blf" else "pcap"})
            settings = repository.load_settings()
            role = Role.CAN if extension == "blf" else Role.ETHERNET
            plan = build_plan(settings, (role,))
            repository.reserve(plan)
            file = plan.files[0]
            file.temp_path.parent.mkdir(parents=True)
            file.temp_path.write_bytes(content)
            repository.close()
            repository = Repository(root / "state.sqlite3")
            repository.recover_incomplete()
            service = RecoveryService(repository)
            row = service.report()["sessions"][0]
            with file.temp_path.open("rb"):
                try:
                    service.publish(plan.session_id, role.value, row["token"], True, tool["path"])
                except OSError:
                    pass
                else:
                    raise AssertionError("An externally open capture was accepted")
            result = service.publish(plan.session_id, role.value, row["token"], True, tool["path"])
            if file.final_path.read_bytes() != content or file.temp_path.exists():
                raise AssertionError("Recovery changed the captured content or left its source behind")
            if result["inspection"].get("packet_count", result["inspection"].get("object_count")) != 0:
                raise AssertionError("Zero-packet recovery was not reported accurately")
            service.finish_session(plan.session_id, service.report()["sessions"][0]["token"], True)
            if repository.captures()[0]["phase"] != "failed" or repository.load_settings().next_index != plan.index + 1:
                raise AssertionError("Recovery certified acquisition success or changed the reserved index")
            report["cases"].append({"case": extension + "_restart_recovery", "passed": True,
                                    "inspection": result["inspection"], "path": str(file.final_path)})
        if service.report()["sessions"] or (output / ".vil_work").exists():
            raise AssertionError("Finished recovery left an incomplete session or empty working folder")
        report.update(passed=True, next_index=repository.load_settings().next_index)
    except Exception as error:
        debug.exception("verification.recovery_failed", error)
        report["error"] = str(error)
    finally:
        if repository:
            repository.close()
        debug.close()
        (root / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def verify_monitoring(data_dir: Path, *, tshark_path: str = "") -> dict:
    root = Path(data_dir)
    if root.exists():
        raise ValueError("Verification requires a new folder; existing profiles are preserved")
    root.mkdir(parents=True)
    configure_worker_environment()
    debug = DebugLogService(root)
    debug.enable()
    runtime = None
    report = {"passed": False, "app_data": str(root), "physical_nic_opened": False,
              "scope": "Generated localhost packets; synthetic test criteria only", "cases": []}
    try:
        tool = _find_tshark(tshark_path)
        if tool["status"] != "ready":
            raise RuntimeError(tool["message_en"])
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            receiver.bind(("127.0.0.1", 0))
            port = receiver.getsockname()[1]
            runtime = Runtime(root, _verification_filter=f"udp dst port {port}")
            runtime.initialize().result(10)
            runtime.save_preferences({"tshark_path": tool["path"], "nic_id": r"\Device\NPF_Loopback"}).result(10)

            def wait_phase(expected, timeout=8):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    runtime._submit(runtime._query).result(5)
                    if runtime.phase == expected:
                        return
                    time.sleep(.1)
                raise AssertionError(f"Expected {expected}, got {runtime.phase}")

            def send(count, delay):
                for number in range(count):
                    sender.sendto(f"AutoLog-monitor-fixture-{number}".encode(), ("127.0.0.1", port))
                    time.sleep(delay)

            def wait_normal(min_packets):
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    runtime._submit(runtime._query).result(5)
                    observed = runtime._snapshots[Role.ETHERNET].observation_details
                    if (runtime.phase == SessionPhase.RECORDING and observed["status"] == "normal"
                            and observed["rules"][0]["matched_packets"] >= min_packets):
                        return observed
                    time.sleep(.02)
                raise AssertionError("Generated receive traffic was not confirmed")

            configured = EthernetRule("generated", "Localhost generated traffic", 1500, 2500, 750, 2,
                                      protocol="UDP", destination_ip="127.0.0.1", expected_ip="127.0.0.1")
            runtime.save_preferences({"monitor_rules_json": encode_rules([configured])}).result(10)
            runtime.toggle((Role.ETHERNET,)).result(30)
            wait_phase(SessionPhase.FAILED)
            report["cases"].append({"case": "initial_missing_auto_stops", "passed": True})
            runtime.toggle((Role.ETHERNET,)).result(30)
            send(1200, .001)
            observed = wait_normal(1200)
            if observed["display_drops"] <= 0:
                raise AssertionError("Display overflow was not exercised")
            runtime.toggle((Role.ETHERNET,)).result(100)
            if runtime.phase != SessionPhase.COMPLETED:
                raise AssertionError("Healthy monitored capture did not finish normally")
            report["cases"].append({"case": "restart_and_independent_monitor_input", "passed": True})
            runtime.toggle((Role.ETHERNET,)).result(30)
            send(10, .02)
            wait_normal(10)
            wait_phase(SessionPhase.FAILED)
            report["cases"].append({"case": "required_receive_stops_mid_capture", "passed": True})
            unexpected = EthernetRule("generated", "Deliberately different expected source", 1500, 2500, 750, 2,
                                      protocol="UDP", destination_ip="127.0.0.1", expected_ip="192.0.2.99")
            runtime.save_preferences({"monitor_rules_json": encode_rules([unexpected])}).result(10)
            runtime.toggle((Role.ETHERNET,)).result(30)
            # One violation is enough to request stop; do not require subsequent
            # fixture packets to survive an intentionally immediate stop.
            send(1, .02)
            wait_phase(SessionPhase.FAILED)
            report["cases"].append({"case": "unexpected_source_auto_stops", "passed": True})
            stored = runtime._submit(runtime._repo.captures).result(10)
            if len(stored) != 4 or sum(item["phase"] == "failed" for item in stored) != 3:
                raise AssertionError("Auto-stop sessions were not distinguished from healthy completion")
            if sum(item["details"]["inspection"]["packet_count"] for item in stored) != 1211:
                raise AssertionError("Generated packet count differs from fully read capture files")
            saved_events = runtime._submit(runtime._repo.recent_events).result(10)
            codes = [event.code for event in saved_events]
            if codes.count("CAPTURE_AUTO_STOP") != 3 or "MONITOR_SOURCE" not in codes:
                raise AssertionError("Auto-stop evidence was not persisted")
            report["cases"].append({"case": "archive_and_persistent_fault_evidence", "passed": True, "packets": 1211})
        if not runtime.request_exit().result(10):
            raise AssertionError("Orderly exit failed")
        report["passed"] = True
    except Exception as error:
        debug.exception("verification.monitor_failed", error)
        report["error"] = str(error)
    finally:
        if runtime:
            runtime.close_for_test()
        debug.close()
        (root / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def verify_ethernet(data_dir: Path, *, tshark_path: str = "") -> dict:
    root = Path(data_dir)
    if root.exists():
        raise ValueError("Verification requires a new folder; existing profiles are preserved")
    root.mkdir(parents=True)
    configure_worker_environment()  # This command has no UI or Qt DLL users.
    debug = DebugLogService(root)
    debug.enable()
    runtime = None
    report = {"passed": False, "app_data": str(root), "scope": "Generated localhost UDP and offline ARP fixture only",
              "physical_nic_opened": False, "cases": []}
    try:
        tool = _find_tshark(tshark_path)
        if tool["status"] != "ready":
            raise RuntimeError(tool["message_en"])
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            receiver.bind(("127.0.0.1", 0))
            port = receiver.getsockname()[1]
            runtime = Runtime(root, _verification_filter=f"udp dst port {port}")
            runtime.initialize().result(timeout=10)
            runtime.save_preferences({"tshark_path": tool["path"], "nic_id": r"\Device\NPF_Loopback",
                                      "monitor_rules_json": encode_rules([])}).result(timeout=10)
            for file_format in ("pcap", "pcapng"):
                runtime.save_preferences({"ethernet_format": file_format}).result(timeout=10)
                for mode in ("zero-packet", "packets", "restart"):
                    runtime.toggle((Role.ETHERNET,)).result(timeout=30)
                    if runtime.phase != SessionPhase.RECORDING:
                        raise AssertionError(f"Capture did not start: {runtime.phase}")
                    expected = 0 if mode == "zero-packet" else 5
                    for number in range(expected):
                        sender.sendto(f"VIL-test-{uuid4().hex}-{number}".encode("ascii"), ("127.0.0.1", port))
                        time.sleep(.03)
                    summaries = []
                    deadline = time.monotonic() + (2 if expected else .2)
                    while time.monotonic() < deadline:
                        summaries.extend(runtime.drain_packets())
                        if len(summaries) >= expected and expected:
                            break
                        time.sleep(.02)
                    runtime.toggle((Role.ETHERNET,)).result(timeout=110)
                    summaries.extend(runtime.drain_packets())
                    if runtime.phase != SessionPhase.COMPLETED:
                        raise AssertionError(f"Capture did not finish: {runtime.phase}")
                    plan = runtime._plan
                    row = runtime._submit(lambda: runtime._repo._connection.execute(
                        "SELECT details FROM sessions WHERE session_id=?", (runtime._plan.session_id,)
                    ).fetchone()[0]).result(timeout=5)
                    inspection = json.loads(row)["inspection"]
                    if inspection["packet_count"] != expected or len(summaries) != expected:
                        raise AssertionError("Capture count or live summaries disagree with generated packets")
                    if any(packet.source != "127.0.0.1" or packet.destination != "127.0.0.1" for packet in summaries):
                        raise AssertionError("Unexpected source in localhost verification")
                    if not plan.files[0].final_path.is_file() or plan.files[0].temp_path.exists():
                        raise AssertionError("Capture was not published to the final location")
                    report["cases"].append({"format": file_format, "mode": mode, "index": plan.index,
                                             "path": str(plan.files[0].final_path), "packets": expected,
                                             "live_summaries": len(summaries), "inspection": inspection})
            if runtime._settings.next_index != 7:
                raise AssertionError("Capture index did not advance exactly once per session")
        report["non_ip"] = _verify_non_ip(root, tool["path"])
        if not runtime.request_exit().result(timeout=10):
            raise AssertionError("Orderly application exit failed")
        report["passed"] = True
    except Exception as error:
        debug.exception("verification.failed", error)
        report["error"] = str(error)
    finally:
        if runtime:
            runtime.close_for_test()
        debug.close()
        (root / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _verify_non_ip(root: Path, tshark_path: str) -> dict:
    # A generated Ethernet/ARP request; read from a fixture, never transmitted.
    frame = bytes.fromhex("ffffffffffff0200000000010806" "0001080006040001"
                          "020000000001c0000201000000000000c0000202")
    path = root / "offline-arp.pcap"
    header = struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
    path.write_bytes(header + struct.pack("<IIII", 1, 0, len(frame), len(frame)) + frame)
    arguments = [tshark_path, "-n", "-r", str(path), "-T", "fields", "-E", "occurrence=f"]
    for field in FIELDS:
        arguments.extend(("-e", field))
    result = subprocess.run(arguments, capture_output=True, text=True, encoding="utf-8", timeout=10,
                            env=external_environment(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise AssertionError(result.stderr)
    packet = parse_summary(result.stdout, "offline-arp")
    if packet.source != "02:00:00:00:00:01" or packet.destination != "ff:ff:ff:ff:ff:ff" or packet.protocol != "ARP":
        raise AssertionError("Non-IP summary did not fall back to Ethernet MAC addresses")
    return {"passed": True, "source": packet.source, "destination": packet.destination, "protocol": packet.protocol}
