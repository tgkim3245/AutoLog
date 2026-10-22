"""Portable capture-tool preference: an empty value means the bundled tools."""

import os
import sys
from pathlib import Path


def bundled_tshark() -> Path:
    root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3]
    return root / "tools" / "Wireshark" / "tshark.exe"


def tshark_candidates(specified: str = "") -> list[Path]:
    return [Path(specified.strip()).expanduser()] if specified.strip() else [bundled_tshark()]


def stored_tshark_path(value: str) -> str:
    """Never persist the absolute location of a relocatable bundled tool."""
    value = value.strip()
    try:
        if value and Path(value).resolve() == bundled_tshark().resolve():
            return ""
    except (OSError, ValueError):
        pass  # Keep invalid explicit input visible; diagnostics reports the error.
    return value


def displayed_tshark_path(value: str) -> str:
    return value or (str(bundled_tshark()) if bundled_tshark().is_file() else "")


def replaces_legacy_managed_tool(value: str) -> bool:
    """Upgrade AutoLog's old managed installation; leave custom selections alone."""
    local = os.environ.get("LOCALAPPDATA")
    if not value or not local or not all(bundled_tshark().with_name(name).is_file()
                                        for name in ("tshark.exe", "dumpcap.exe", "capinfos.exe")):
        return False
    try:
        return Path(value).resolve() in {
            (Path(local) / app / "tools" / folder / "tshark.exe").resolve()
            for app in ("AutoLog", "Auto_Log", "VILLogging")
            for folder in ("Wireshark", "WiresharkPortable/App/Wireshark")}
    except (OSError, ValueError):
        return False
