"""Bounded, local environment discovery without connecting to capture devices.

File presence, COM registration, and a tool's version response are separate
observations. None establishes licensing, live NIC access, or capture support.
"""

from __future__ import annotations

import importlib.metadata
import logging
import os
import platform
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

from vil_logging import __version__
from vil_logging.contracts.models import utc_now

logger = logging.getLogger(__name__)
_VERSION_TIMEOUT_SECONDS = 3
_TEXT_LIMIT = 8192


def _text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")[:_TEXT_LIMIT]
    return (value or "")[:_TEXT_LIMIT]


def _program_folders() -> list[Path]:
    values = [os.environ.get("ProgramFiles", r"C:\Program Files"),
              os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")]
    return list(dict.fromkeys(Path(value) for value in values))


def _tool_candidates(name: str, *, specified: str = "", sibling_dir: Path | None = None) -> list[Path]:
    if specified:
        # Explicit settings never silently switch to a different installation.
        return [Path(specified).expanduser()]
    if name == "tshark":
        return []  # Capture executable is always chosen explicitly by the user.
    candidates = []
    if sibling_dir is not None:
        candidates.append(sibling_dir / f"{name}.exe")
    if found := shutil.which(f"{name}.exe") or shutil.which(name):
        candidates.append(Path(found))
    candidates.extend(folder / "Wireshark" / f"{name}.exe" for folder in _program_folders())
    if local_app_data := os.environ.get("LOCALAPPDATA"):
        for app_name in ("AutoLog", "Auto_Log", "VILLogging"):
            root = Path(local_app_data) / app_name / "tools"
            candidates.extend((root / "Wireshark" / f"{name}.exe",
                               root / "WiresharkPortable" / "App" / "Wireshark" / f"{name}.exe"))
    return list(dict.fromkeys(candidates))


def _version_response(path: Path) -> dict[str, Any]:
    arguments = [str(path), "--version"]
    logger.debug("diagnostics.tool_version_requested", extra={"arguments": arguments})
    try:
        result = subprocess.run(
            arguments, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_VERSION_TIMEOUT_SECONDS, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as error:
        logger.warning("diagnostics.tool_version_timeout", extra={"path": str(path)})
        return {"status": "unknown", "reason": "timeout", "timeout_seconds": _VERSION_TIMEOUT_SECONDS,
                "stdout": _text(error.stdout), "stderr": _text(error.stderr), "original": str(error)}
    except OSError as error:
        logger.exception("diagnostics.tool_version_failed", extra={"path": str(path)})
        return {"status": "unavailable", "reason": "execution_failed", "original": str(error)}
    output, errors = _text(result.stdout), _text(result.stderr)
    status = "present" if result.returncode == 0 and (output.strip() or errors.strip()) else "unknown"
    logger.debug("diagnostics.tool_version_result", extra={
        "path": str(path), "return_code": result.returncode, "status": status,
        "stdout": output, "stderr": errors,
    })
    return {"status": status, "return_code": result.returncode, "stdout": output, "stderr": errors}


def _discover_tool(name: str, *, specified: str = "", sibling_dir: Path | None = None) -> dict[str, Any]:
    candidates = _tool_candidates(name, specified=specified, sibling_dir=sibling_dir)
    errors = []
    selected = None
    for candidate in candidates:
        try:
            if candidate.is_file():
                selected = candidate.resolve()
                break
        except OSError as error:
            errors.append({"path": str(candidate), "original": str(error)})
    report: dict[str, Any] = {
        "status": "present" if selected else ("unknown" if errors else "unavailable"),
        "path": str(selected) if selected else "",
        "checked_paths": [str(candidate) for candidate in candidates],
        "discovery_errors": errors,
        "explicit_path": bool(specified),
        "scope": "User-selected executable; no live capture" if name == "tshark" else
                 "Sibling tools, PATH and known Wireshark folders; no live capture",
        "capture_check": "not_performed",
    }
    if selected is not None:
        report["version_check"] = _version_response(selected)
    else:
        report["version_check"] = {"status": "unavailable", "reason": "executable_not_found"}
    return report


def _canoe_registration() -> dict[str, Any]:
    if os.name != "nt":
        return {"status": "unknown", "reason": "Windows registry is unavailable", "entries": []}
    try:
        import winreg
    except ImportError as error:
        return {"status": "unknown", "original": str(error), "entries": []}
    entries, errors = [], []
    for view_name, view_flag in (("64", winreg.KEY_WOW64_64KEY), ("32", winreg.KEY_WOW64_32KEY)):
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"CANoe.Application\CLSID", 0,
                                winreg.KEY_READ | view_flag) as key:
                clsid, _ = winreg.QueryValueEx(key, None)
                entries.append({"progid": "CANoe.Application", "registry_view_bits": view_name,
                                "clsid": str(clsid)})
        except FileNotFoundError:
            continue
        except OSError as error:
            errors.append({"registry_view_bits": view_name, "original": str(error)})
    return {"status": "present" if entries else ("unknown" if errors else "unavailable"),
            "entries": entries, "errors": errors, "activation_check": "not_performed"}


def _file_version(path: Path) -> dict[str, Any]:
    if os.name != "nt":
        return {"status": "unknown", "reason": "Windows file version API is unavailable"}
    try:
        import win32api

        info = win32api.GetFileVersionInfo(str(path), "\\")
        high, low = info["FileVersionMS"], info["FileVersionLS"]
        version = f"{high >> 16}.{high & 0xFFFF}.{low >> 16}.{low & 0xFFFF}"
        return {"status": "present", "file_version": version}
    except (ImportError, OSError, KeyError) as error:
        return {"status": "unknown", "original": str(error)}
    except Exception as error:
        # pywin32's API-specific exception may not derive from OSError.
        logger.debug("diagnostics.file_version_unavailable", exc_info=True, extra={"path": str(path)})
        return {"status": "unknown", "original": str(error)}


def _discover_canoe() -> dict[str, Any]:
    executables, checked, errors = [], [], []
    for folder in _program_folders():
        try:
            installations = sorted(folder.glob("Vector CANoe*"), key=str, reverse=True)
            for installation in installations:
                path = installation / "Exec64" / "CANoe64.exe"
                checked.append(str(path))
                if path.is_file():
                    executables.append({"path": str(path), "version_check": _file_version(path)})
        except OSError as error:
            errors.append({"path": str(folder), "original": str(error)})
    return {
        "status": "present" if executables else ("unknown" if errors else "unavailable"),
        "executables": executables, "checked_paths": checked,
        "search_roots": [str(folder) for folder in _program_folders()], "errors": errors,
        "com_registration": _canoe_registration(),
        "scope": "Known Vector CANoe*/Exec64 paths, file versions, and COM registry only",
        "license_check": "not_performed", "com_activation_check": "not_performed",
        "measurement_check": "not_performed", "independent_instances_check": "not_performed",
    }


def _discover_npcap() -> dict[str, Any]:
    windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    candidates = [windows / "System32" / "Npcap" / "wpcap.dll",
                  windows / "System32" / "Npcap" / "Packet.dll",
                  windows / "System32" / "drivers" / "npcap.sys"]
    files, errors = [], []
    for candidate in candidates:
        try:
            if candidate.is_file():
                files.append(str(candidate))
        except OSError as error:
            errors.append({"path": str(candidate), "original": str(error)})
    return {"status": "present" if files else ("unknown" if errors else "unavailable"),
            "files": files, "checked_paths": [str(path) for path in candidates], "errors": errors,
            "scope": "Known Npcap DLL and driver paths only",
            "driver_loaded_check": "not_performed", "nic_access_check": "not_performed"}


def _package_versions() -> dict[str, Any]:
    packages = {}
    for name in ("PySide6", "pywin32", "pyinstaller"):
        try:
            packages[name] = {"status": "present", "version": importlib.metadata.version(name)}
        except importlib.metadata.PackageNotFoundError:
            packages[name] = {"status": "unavailable"}
    return packages


def _platform_info() -> dict[str, str]:
    if os.name == "nt":
        # Python 3.14 platform.uname()/system()/machine() may internally run
        # ``cmd /c ver`` without our timeout/hidden-console guarantees.
        version = sys.getwindowsversion()
        return {
            "system": "Windows", "release": f"{version.major}.{version.minor}",
            "version": f"{version.major}.{version.minor}.{version.build}",
            "machine": os.environ.get("PROCESSOR_ARCHITEW6432")
            or os.environ.get("PROCESSOR_ARCHITECTURE", "unknown"),
        }
    return {"system": platform.system(), "release": platform.release(),
            "version": platform.version(), "machine": platform.machine()}


def collect_environment(tshark_path: str = "") -> dict[str, Any]:
    """Return JSON-serializable local observations; never launch CANoe/capture.

    Version queries are the only child processes, each with a three-second
    timeout and hidden Windows console. No installation or registry mutation is
    performed. Discovery is bounded to known paths and is not an entire disk scan.
    """
    logger.info("diagnostics.environment_started", extra={"specified_tshark_path": tshark_path})
    tshark = _discover_tool("tshark", specified=tshark_path)
    sibling = Path(tshark["path"]).parent if tshark["path"] else None
    result = {
        "timestamp_utc": utc_now(),
        "app": {"version": __version__, "packages": _package_versions()},
        "python": {"version": platform.python_version(), "executable": sys.executable,
                   "pointer_bits": struct.calcsize("P") * 8, "frozen": bool(getattr(sys, "frozen", False))},
        "platform": _platform_info(),
        "canoe": _discover_canoe(), "tshark": tshark,
        "dumpcap": _discover_tool("dumpcap", sibling_dir=sibling),
        "capinfos": _discover_tool("capinfos", sibling_dir=sibling),
        "npcap": _discover_npcap(),
        "scope": "Local files, package metadata, COM registration, and version commands only",
        "hardware_checks": "not_performed", "network_access": "not_used",
    }
    logger.info("diagnostics.environment_completed", extra={
        "canoe_status": result["canoe"]["status"], "tshark_status": tshark["status"],
        "npcap_status": result["npcap"]["status"],
    })
    return result
