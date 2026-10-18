"""External tools run outside the frozen application's DLL search directory."""

import ctypes
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def configure_worker_environment() -> None:
    """Call in a dedicated worker only, never change the UI process DLL search."""
    if os.name == "nt":
        ctypes.windll.kernel32.SetDllDirectoryW(None)


def external_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment["LC_ALL"] = "C"
    if getattr(sys, "frozen", False):
        internal = str(Path(sys._MEIPASS).resolve()).casefold()
        environment["PATH"] = os.pathsep.join(
            value for value in environment.get("PATH", "").split(os.pathsep)
            if value and not str(Path(value).resolve()).casefold().startswith(internal)
        )
        if "LD_LIBRARY_PATH_ORIG" in environment:
            environment["LD_LIBRARY_PATH"] = environment["LD_LIBRARY_PATH_ORIG"]
        else:
            environment.pop("LD_LIBRARY_PATH", None)
    return environment


def launch_capture(arguments: list[str]) -> subprocess.Popen:
    options = {}
    if os.name == "nt":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        # A private hidden console isolates normal Ctrl+Break from all other
        # applications, including a separately running Wireshark.
        options.update(creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=startup)
    else:
        options["start_new_session"] = True
    return subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=external_environment(), **options)


def request_normal_stop(process: subprocess.Popen) -> None:
    """Signal only our child/private console; never terminate a recorder here."""
    if process.poll() is not None:
        return
    if os.name != "nt":
        os.killpg(process.pid, signal.SIGINT)
        return
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    handler_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_ulong)
    handler = handler_type(lambda _event: True)
    kernel.FreeConsole()  # This dedicated worker may have inherited a developer console.
    if not kernel.AttachConsole(process.pid):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not kernel.SetConsoleCtrlHandler(handler, True):
            raise ctypes.WinError(ctypes.get_last_error())
        if process.poll() is not None:
            return
        if not kernel.GenerateConsoleCtrlEvent(1, 0):  # CTRL_BREAK_EVENT, our isolated console.
            raise ctypes.WinError(ctypes.get_last_error())
        time.sleep(0.05)
    finally:
        kernel.FreeConsole()
