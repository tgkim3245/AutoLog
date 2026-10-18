"""Discover local capture tools and friendly Windows NIC names without capture.

Only version, interface-list, and read-only OS adapter queries are issued. A
listed interface is a selectable candidate, not proof that live capture works.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any
from uuid import UUID

from vil_logging.diagnostics.environment import (
    _discover_npcap,
    _text,
    _tool_candidates,
    _version_response,
)

logger = logging.getLogger(__name__)
_QUERY_TIMEOUT = 8
_LIST_TIMEOUT = 3
_MAX_LIST_TEXT = 256 * 1024
_NPF_PREFIX = "\\Device\\NPF_"
_POWERSHELL_ADAPTER_QUERY = (
    "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; "
    "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); "
    "@(Get-NetAdapter -ErrorAction Stop | Select-Object "
    "Name,InterfaceDescription,@{Name='InterfaceGuid';Expression={$_.InterfaceGuid.ToString()}},"
    "MacAddress,@{Name='Status';Expression={$_.Status.ToString()}}) "
    "| ConvertTo-Json -Compress -Depth 3"
)


def _nic_key(value: str) -> str:
    value = value.strip()
    candidate = value[len(_NPF_PREFIX):] if value.lower().startswith(_NPF_PREFIX.lower()) else value
    try:
        return str(UUID(candidate.strip("{}"))).upper()
    except (ValueError, AttributeError):
        return value.casefold()


def _canonical_nic_id(value: str) -> str | None:
    key = _nic_key(value)
    try:
        return _NPF_PREFIX + "{" + str(UUID(key)).upper() + "}"
    except ValueError:
        if value.strip().casefold() == (_NPF_PREFIX + "Loopback").casefold():
            return _NPF_PREFIX + "Loopback"
        return None


def _parse_tshark_interfaces(output: str) -> list[dict[str, Any]]:
    interfaces = []
    seen = set()
    for line in output.splitlines():
        match = re.fullmatch(r"\s*\d+\.\s+(\S+)(?:\s+\((.*)\))?\s*", line)
        if not match or (identifier := _canonical_nic_id(match[1])) is None:
            continue
        if identifier in seen:
            continue
        seen.add(identifier)
        description = (match[2] or "").strip()
        interfaces.append({
            "id": identifier, "name": description or identifier,
            "description": description, "status": "unknown", "mac": "",
            "capture_available": True, "source": "tshark",
        })
    return interfaces


def _run_query(arguments: list[str], *, timeout: int) -> dict[str, Any]:
    logger.debug("connections.query_requested", extra={"arguments": arguments, "timeout": timeout})
    started = time.monotonic()
    try:
        result = subprocess.run(
            arguments, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        stdout = result.stdout or ""
        if len(stdout) > _MAX_LIST_TEXT:
            response = {"success": False, "detail": "Interface-list output exceeded the supported limit"}
        else:
            response = {"success": result.returncode == 0, "stdout": stdout,
                        "stderr": _text(result.stderr), "return_code": result.returncode,
                        "detail": _text(result.stderr) if result.returncode else ""}
    except subprocess.TimeoutExpired as error:
        logger.warning("connections.query_timed_out", exc_info=True, extra={"arguments": arguments})
        response = {"success": False, "reason": "timeout", "detail": str(error),
                    "stdout": _text(error.stdout), "stderr": _text(error.stderr)}
    except OSError as error:
        logger.exception("connections.query_failed", extra={"arguments": arguments})
        response = {"success": False, "reason": "execution_failed", "detail": str(error)}
    logger.debug("connections.query_completed", extra={
        "arguments": arguments, "success": response["success"],
        "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
        "detail": response.get("detail", ""),
    })
    return response


def _windows_interfaces() -> tuple[list[dict[str, Any]], str]:
    if os.name != "nt":
        return [], "Friendly Windows adapter discovery is unavailable on this operating system"
    powershell = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
                  / "WindowsPowerShell" / "v1.0" / "powershell.exe")
    query = _run_query(
        [str(powershell), "-NoProfile", "-NonInteractive", "-Command", _POWERSHELL_ADAPTER_QUERY],
        timeout=_QUERY_TIMEOUT,
    )
    if not query["success"]:
        return [], query.get("detail") or query.get("stderr") or "Windows adapter query failed"
    text = query.get("stdout", "").lstrip("\ufeff").strip()
    try:
        adapters = json.loads(text) if text else []
    except json.JSONDecodeError as error:
        return [], f"Windows adapter output was not valid JSON: {error}"
    if isinstance(adapters, dict):
        adapters = [adapters]
    if adapters is None:
        adapters = []
    if not isinstance(adapters, list):
        return [], "Windows adapter output was not an adapter list"
    result = []
    seen = set()
    for adapter in adapters:
        if not isinstance(adapter, dict):
            continue
        raw_guid = adapter.get("InterfaceGuid")
        if not isinstance(raw_guid, str) or (identifier := _canonical_nic_id(raw_guid)) is None:
            continue
        if identifier in seen:
            continue
        seen.add(identifier)
        raw_status = str(adapter.get("Status") or "").casefold().replace(" ", "")
        status = "up" if raw_status == "up" else (
            "down" if raw_status in {"down", "disconnected", "disabled", "notpresent", "lowerlayerdown"}
            else "unknown"
        )
        description = str(adapter.get("InterfaceDescription") or "")
        result.append({
            "id": identifier, "name": str(adapter.get("Name") or description or identifier),
            "description": description, "status": status,
            "mac": str(adapter.get("MacAddress") or ""),
            "capture_available": False, "source": "windows",
        })
    return result, ""


def _find_tshark(tshark_path: str) -> dict[str, Any]:
    specified = tshark_path.strip()
    candidates = _tool_candidates("tshark", specified=specified)
    if not specified and (local_app_data := os.environ.get("LOCALAPPDATA")):
        for app_name in ("AutoLog", "Auto_Log", "VILLogging"):
            tool_root = Path(local_app_data) / app_name / "tools"
            candidates.extend((tool_root / "Wireshark" / "tshark.exe",
                               tool_root / "WiresharkPortable" / "App" / "Wireshark" / "tshark.exe"))
    attempted = []
    for candidate in dict.fromkeys(candidates):
        try:
            if not candidate.is_file():
                continue
            resolved = candidate.resolve()
        except OSError as error:
            attempted.append(f"{candidate}: {error}")
            continue
        version = _version_response(resolved)
        output = version.get("stdout", "") or version.get("stderr", "")
        if version.get("status") == "present" and re.search(r"\bTShark\b", output, re.I):
            return {
                "status": "ready", "path": str(resolved),
                "version": next((line.strip()[:180] for line in output.splitlines() if line.strip()), ""),
                "message_ko": "TShark를 찾았습니다. 아래에서 사용할 연결을 선택하세요.",
                "message_en": "TShark was found. Select the connection below.",
                "detail": "Version command succeeded; live capture has not been tested.",
                "automatic": not bool(specified),
            }
        attempted.append(f"{candidate}: " + (
            version.get("original") or version.get("reason") or output or "TShark version was not confirmed"
        ))
    invalid = bool(specified or attempted)
    return {
        "status": "invalid" if invalid else "missing", "path": specified, "version": "",
        "message_ko": ("저장된 TShark 경로를 사용할 수 없습니다. 다시 찾거나 프로그램을 선택하세요."
                       if specified else ("찾은 TShark를 실행할 수 없습니다. 경로와 설치 상태를 확인하세요."
                                          if invalid else "TShark를 찾지 못했습니다. Wireshark 설치 후 다시 찾기를 누르세요.")),
        "message_en": ("The saved TShark path is unavailable. Find it again or select the program."
                       if specified else ("The discovered TShark could not be verified. Check its installation."
                                          if invalid else "TShark was not found. Install Wireshark, then find it again.")),
        "detail": "\n".join(attempted)[:8192] if attempted else (
            f"Executable not found: {specified}" if specified else
            "Checked PATH and known Wireshark installation folders."
        ),
        "automatic": not bool(specified),
    }


def _npcap_report() -> dict[str, Any]:
    found = _discover_npcap()
    status = {"present": "present", "unavailable": "missing"}.get(found["status"], "unknown")
    messages = {
        "present": ("Npcap 설치 파일을 확인했습니다. 실제 캡처는 아직 검사하지 않았습니다.",
                    "Npcap files were found. Live capture has not been tested."),
        "missing": ("알려진 경로에서 Npcap을 찾지 못했습니다. Ethernet 캡처에 필요한 드라이버를 확인하세요.",
                    "Npcap was not found in known locations. Check the driver needed for Ethernet capture."),
        "unknown": ("Npcap 설치 상태를 확인하지 못했습니다. 상세 오류를 확인하세요.",
                    "Npcap installation could not be checked. Review the error details."),
    }
    return {"status": status, "message_ko": messages[status][0], "message_en": messages[status][1],
            "detail": found}


def discover_connections(tshark_path: str = "", nic_id: str = "") -> dict[str, Any]:
    """Find TShark and merge friendly OS NICs with stable NPF capture IDs.

    ``capture_available`` means listed by ``tshark -D`` only. This function never
    opens an interface for capture and never selects the first available NIC.
    A remembered GUID is kept only if it matches a currently discovered NIC.
    """
    started = time.monotonic()
    logger.info("connections.discovery_started", extra={
        "tshark_path": tshark_path, "remembered_nic_id": nic_id,
    })
    windows, windows_error = _windows_interfaces()
    tshark = _find_tshark(tshark_path)
    capture, list_error = [], ""
    if tshark["status"] == "ready":
        listing = _run_query([tshark["path"], "-D"], timeout=_LIST_TIMEOUT)
        if listing["success"]:
            capture = _parse_tshark_interfaces(listing.get("stdout", ""))
        else:
            list_error = listing.get("detail") or listing.get("stderr") or "TShark interface query failed"
    merged = {_nic_key(interface["id"]): interface for interface in windows}
    for interface in capture:
        key = _nic_key(interface["id"])
        if key in merged:
            merged[key] = {**merged[key], "capture_available": True, "source": "tshark"}
        else:
            merged[key] = interface
    interfaces = sorted(merged.values(), key=lambda interface: (
        not interface["capture_available"], interface["name"].casefold(), interface["id"],
    ))
    remembered = _nic_key(nic_id) if nic_id.strip() else ""
    selected = next((interface["id"] for interface in interfaces
                     if remembered and _nic_key(interface["id"]) == remembered), "")
    result = {
        "tshark": tshark, "interfaces": interfaces, "selected_nic_id": selected,
        "remembered_nic_missing": bool(remembered and not selected), "npcap": _npcap_report(),
        "capture_check": "not_performed", "windows_query_error": windows_error,
        "interface_query_error": list_error,
    }
    errors = [error for error in (windows_error, list_error) if error]
    if errors:
        result["detail"] = "\n".join(errors)
    logger.info("connections.discovery_completed", extra={
        "tshark_status": tshark["status"], "interface_count": len(interfaces),
        "capture_candidate_count": len(capture), "selected_nic_id": selected,
        "remembered_nic_missing": result["remembered_nic_missing"],
        "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
        "errors": errors,
        "report": result,
    })
    return result
