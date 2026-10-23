"""Prepare CANoe's required independent-client mode before creating any instance."""

import ctypes
import logging
import os
import re
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path
from uuid import uuid4

log = logging.getLogger(__name__)
SETTING = re.compile(rb"(?m)^(SingleCOMClient[ \t]*=[ \t]*)([01])([ \t]*\r?)$")


class CanoeActivationError(RuntimeError):
    def __init__(self, issue, message, *, path="", process_ids=(), diagnostics=None):
        self.connection_issue = issue
        self.settings_path = str(path)
        self.process_ids = list(process_ids)
        self.diagnostics = diagnostics or {}
        super().__init__(message)


@contextmanager
def activation_guard():
    """Serialize setup and activation across CAN/Diag worker processes."""
    import win32event

    handle = win32event.CreateMutex(None, False, r"Local\AutoLog.CANoeActivation")
    try:
        acquired = win32event.WaitForSingleObject(handle, 30_000)
        if acquired not in (win32event.WAIT_OBJECT_0, win32event.WAIT_ABANDONED):
            raise TimeoutError("Timed out waiting for the other CANoe connection to finish opening.")
        try:
            yield
        finally:
            win32event.ReleaseMutex(handle)
    finally:
        handle.Close()


def ensure_independent_activation():
    """Mandatory connection prerequisite, applied automatically with an original backup.

    Existing CANoe processes must be closed once if they started in shared mode.
    They are never stopped or reconfigured by this helper.
    Caller holds activation_guard through subsequent DispatchEx activation.
    """
    path = ""
    try:
        path = registered_settings_file()
        expected = path.read_bytes()
        matches = list(SETTING.finditer(expected))
        if len(matches) != 1:
            raise ValueError("Expected exactly one SingleCOMClient=0 or 1 entry in can.ini.")
        if matches[0][2] == b"1":
            return {"changed": False, "path": str(path), "enabled": True}
        processes = canoe_process_ids()
        if processes:
            raise CanoeActivationError(
                "restart_required", "CANoe is running in shared COM mode. Save your work and close all CANoe "
                "windows once, then reconnect. One Click Log will prepare independent connections automatically.",
                path=path, process_ids=processes)
        result = set_single_client(path, True, expected=expected)
        log.info("canoe.independent_mode_prepared", extra={"fields": result})
        return result
    except CanoeActivationError:
        raise
    except Exception as error:
        raise CanoeActivationError(
            "setup_failed", f"Could not prepare required independent CANoe connections: {error}", path=path) from error


def _registration_error(issue, message, **observed):
    """Read-only repair guidance; never guess a version or rewrite COM registry keys."""
    from .environment import _discover_canoe

    try:
        tools = []
        for item in _discover_canoe().get("executables", []):
            executable = Path(item["path"])
            utility = executable.with_name("RegisterComponents.exe")
            if utility.is_file():
                tools.append({"executable": str(executable), "registration_tool": str(utility),
                              "version": item.get("version_check", {}).get("file_version", "")})
        observed["repair_tools"] = tools
    except Exception as error:
        observed["repair_discovery_error"] = str(error)
    observed["registry_modified"] = False
    log.error("canoe.com_registration_failed", extra={"fields": {"issue": issue, **observed}})
    return CanoeActivationError(issue, message + " Run the intended installed CANoe version's "
        "Exec64/RegisterComponents.exe as administrator, then reconnect. Installing or uninstalling "
        "another CANoe version can change or remove COM registration.", diagnostics=observed)


def registered_executable():
    """Resolve the automation server, distinguishing absent/stale COM entries."""
    import winreg

    progid_key = r"CANoe.Application\CLSID"
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid_key) as key:
            clsid = winreg.QueryValueEx(key, None)[0]
    except FileNotFoundError as error:
        raise _registration_error("com_registration_missing", "CANoe COM registration is missing.",
                                  registry_key=progid_key) from error
    if not isinstance(clsid, str) or not re.fullmatch(r"\{[0-9a-fA-F-]{36}\}", clsid):
        raise _registration_error("com_registration_invalid", "CANoe COM class registration is invalid.",
                                  registry_key=progid_key, registered_clsid=str(clsid))
    server_key = rf"CLSID\{clsid}\LocalServer32"
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, server_key) as key:
            command = winreg.QueryValueEx(key, None)[0]
    except FileNotFoundError as error:
        raise _registration_error("com_registration_invalid", "CANoe COM server registration is missing.",
                                  registry_key=server_key, registered_clsid=clsid) from error
    if not isinstance(command, str):
        raise _registration_error("com_registration_invalid", "CANoe COM server command is invalid.",
                                  registry_key=server_key, registered_command=str(command))
    match = re.match(r'^\s*"([^"]+\.exe)"|^\s*(.+?\.exe)(?:\s|$)', command, re.I)
    if not match:
        raise _registration_error("com_registration_invalid", "The registered CANoe executable could not be identified.",
                                  registry_key=server_key, registered_command=command)
    executable = Path(match[1] or match[2]).resolve()
    if not executable.is_file() or executable.name.casefold() not in {"canoe.exe", "canoe32.exe", "canoe64.exe"}:
        raise _registration_error("com_registration_invalid", "The registered CANoe executable is absent or invalid.",
                                  registry_key=server_key, registered_command=command,
                                  registered_executable=str(executable))
    return executable


def registered_settings_file(application_path=None):
    """Match the registered COM executable to Vector's recorded SettingsFolder."""
    import winreg

    executable = registered_executable()
    if (application_path and
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


def registration_guidance(diagnostics, language):
    language = language if language in {"ko", "en", "zh"} else "ko"
    messages = {
        "ko": "CANoe 자동 연결(COM) 등록이 없거나 올바르지 않습니다. 설치 버전의 등록 복구가 필요합니다.",
        "en": "CANoe automation (COM) registration is missing or invalid. Re-register the installed version.",
        "zh": "CANoe 自动连接（COM）注册缺失或无效，请修复所用版本的注册。",
    }
    instructions = {
        "ko": "다른 CANoe 버전 설치·제거 후 자동 연결 등록이 바뀌거나 사라질 수 있습니다. "
              "모든 CANoe 작업을 저장하고 창을 닫은 뒤, 사용할 버전의 Exec64\\RegisterComponents.exe를 "
              "우클릭하여 관리자 권한으로 실행하세요. 완료 후 이 카드의 연결 확인을 다시 누르세요. "
              "여러 버전이 있으면 사용할 버전 하나만 등록하세요. 도구가 없으면 해당 CANoe 설치 복구를 사용하세요.",
        "en": "Installing or removing another CANoe version can change or remove automation registration. "
              "Save your work and close all CANoe windows. Run the intended version's "
              "Exec64\\RegisterComponents.exe as administrator, then check this connection again. "
              "With multiple versions, register only the one you intend to use. If the tool is absent, repair that CANoe installation.",
        "zh": "安装或卸载其他 CANoe 版本可能改变或删除自动连接注册。请保存工作并关闭所有 CANoe 窗口，"
              "右键以管理员身份运行所用版本的 Exec64\\RegisterComponents.exe，完成后再次检查此连接。"
              "存在多个版本时只注册要使用的版本。工具缺失时请修复对应的 CANoe 安装。",
    }
    actions = {
        "ko": "공식 등록 도구 실행 → 관리자 권한 승인 → 연결 확인. 자세한 방법은 사용법의 CANoe 등록 복구를 보세요.",
        "en": "Run the official registration tool → approve administrator access → check connection. See CANoe registration repair in Guide.",
        "zh": "运行官方注册工具 → 允许管理员权限 → 检查连接。详情参阅使用指南的 CANoe 注册修复。",
    }
    tools = "\n".join(item["registration_tool"] for item in diagnostics.get("repair_tools", [])
                      if isinstance(item, dict) and item.get("registration_tool"))
    return messages[language], instructions[language] + ("\n\n" + tools if tools else ""), actions[language]


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
    """One-byte mode change with exclusive handle, backup, readback and no elevation."""
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
