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
from vil_logging.runtime import Runtime
from vil_logging.storage.file_access import observe
from vil_logging.storage.file_service import FileService
from vil_logging.storage.naming import build_plan
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


def verify_ethernet(data_dir: Path) -> dict:
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
        tool = _find_tshark("")
        if tool["status"] != "ready":
            raise RuntimeError(tool["message_en"])
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            receiver.bind(("127.0.0.1", 0))
            port = receiver.getsockname()[1]
            runtime = Runtime(root, _verification_filter=f"udp dst port {port}")
            runtime.initialize().result(timeout=10)
            runtime.save_preferences({"tshark_path": tool["path"], "nic_id": r"\Device\NPF_Loopback"}).result(timeout=10)
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
