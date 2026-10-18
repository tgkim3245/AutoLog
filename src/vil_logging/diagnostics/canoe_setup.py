"""Explicit CANoe COM setup; never mutate global settings during connection."""

import ctypes
import logging
import os
import re
from ctypes import wintypes
from pathlib import Path
from uuid import uuid4

log = logging.getLogger(__name__)
SETTING = re.compile(rb"(?m)^(SingleCOMClient[ \t]*=[ \t]*)([01])([ \t]*\r?)$")


class IndependentConnectionsRequired(RuntimeError):
    def __init__(self, path, process_ids):
        self.settings_path = str(path)
        self.process_ids = process_ids
        super().__init__("Independent CANoe connections are disabled while a CANoe window is open. "
                         "Save your work, close all CANoe windows, and enable independent connections in AutoLog.")


def check_activation():
    """Read-only preflight before COM creation; never activate an existing project."""
    try:
        path = registered_settings_file()
        enabled = single_client_enabled(path)
        processes = canoe_process_ids()
    except (OSError, ValueError) as error:
        # Retain the existing identity/configuration checks if settings cannot be read.
        log.warning("canoe.activation_preflight_unavailable", extra={"fields": {"error": str(error)}})
        return
    if not enabled and processes:
        raise IndependentConnectionsRequired(path, processes)


def registered_settings_file(application_path=None):
    """Match the registered COM executable to Vector's recorded SettingsFolder."""
    import winreg

    with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"CANoe.Application\CLSID") as key:
        clsid = winreg.QueryValueEx(key, None)[0]
    with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{clsid}\LocalServer32") as key:
        command = winreg.QueryValueEx(key, None)[0]
    match = re.match(r'^\s*"([^"]+\.exe)"|^\s*(.+?\.exe)(?:\s|$)', command, re.I)
    if not match:
        raise ValueError("The registered CANoe executable could not be identified.")
    executable = Path(match[1] or match[2]).resolve()
    if not executable.is_file() or (application_path and
            str(executable).casefold() != str(Path(application_path).resolve()).casefold()):
        raise ValueError("The active CANoe version differs from the registered COM server.")
    candidates = set()
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Vector\CANoe") as root:
        for index in range(winreg.QueryInfoKey(root)[0]):
            with winreg.OpenKey(root, winreg.EnumKey(root, index)) as key:
                try:
                    install = Path(winreg.QueryValueEx(key, "Path")[0]).resolve()
                    folder = Path(winreg.QueryValueEx(key, "SettingsFolder")[0])
                except FileNotFoundError:
                    continue
                if str(install).casefold() == str(executable.parent.parent).casefold():
                    candidates.add((folder / "can.ini").resolve())
    if len(candidates) != 1:
        raise ValueError("Cannot uniquely locate can.ini for the registered CANoe version.")
    return candidates.pop()


def single_client_enabled(path):
    matches = list(SETTING.finditer(Path(path).read_bytes()))
    if len(matches) != 1:
        raise ValueError("Expected exactly one SingleCOMClient=0 or 1 entry in can.ini.")
    return matches[0][2] == b"1"


def canoe_process_ids():
    """Read a process snapshot without activating COM or terminating anything."""
    class ProcessEntry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    api.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    api.Process32FirstW.argtypes = api.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry))
    api.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = api.CreateToolhelp32Snapshot(2, 0)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        item = ProcessEntry()
        item.dwSize = ctypes.sizeof(item)
        found = api.Process32FirstW(handle, ctypes.byref(item))
        if not found:
            raise ctypes.WinError(ctypes.get_last_error())
        result = []
        while found:
            if item.szExeFile.casefold() in {"canoe.exe", "canoe32.exe", "canoe64.exe"}:
                result.append(item.th32ProcessID)
            found = api.Process32NextW(handle, ctypes.byref(item))
        if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
            raise ctypes.WinError(ctypes.get_last_error())
        return result
    finally:
        api.CloseHandle(handle)


def set_single_client(path, enabled, *, expected):
    """User-requested one-byte change, exclusive handle, backup, readback, no elevation."""
    import win32file

    if canoe_process_ids():
        raise RuntimeError("Close all CANoe windows before changing COM activation settings.")
    path = Path(path)
    handle = win32file.CreateFile(str(path), 0xC0000000, 0, None, 3, 0x00200000, None)
    try:
        info = win32file.GetFileInformationByHandle(handle)
        if info[0] & 0x400 or info[7] != 1:
            raise ValueError("can.ini must be a regular file without links.")
        size = win32file.GetFileSize(handle)
        if size > 4 * 1024 * 1024:
            raise ValueError("Unexpectedly large can.ini; no change was made.")
        original = win32file.ReadFile(handle, size)[1]
        if original != expected:
            raise RuntimeError("can.ini changed since it was displayed. Reopen setup and review it again.")
        matches = list(SETTING.finditer(original))
        if len(matches) != 1:
            raise ValueError("Expected exactly one SingleCOMClient setting; no change was made.")
        value = b"1" if enabled else b"0"
        if matches[0][2] == value:
            return {"changed": False, "path": str(path), "enabled": enabled}
        backup = path.with_name(path.name + ".AutoLog-" + uuid4().hex[:12] + ".bak")
        with backup.open("xb") as destination:
            destination.write(original)
            destination.flush()
            os.fsync(destination.fileno())
        if canoe_process_ids():
            raise RuntimeError("CANoe started during setup; no setting was changed.")
        offset = matches[0].start(2)
        changed = original[:offset] + value + original[offset + 1:]
        win32file.SetFilePointer(handle, offset, 0)
        win32file.WriteFile(handle, value)
        win32file.FlushFileBuffers(handle)
        win32file.SetFilePointer(handle, 0, 0)
        if win32file.ReadFile(handle, size)[1] != changed:
            raise RuntimeError(f"Setting readback failed. Original backup: {backup}")
        result = {"changed": True, "path": str(path), "enabled": enabled, "backup": str(backup)}
        log.info("canoe.com_setup_changed", extra={"fields": result})
        return result
    finally:
        handle.Close()
