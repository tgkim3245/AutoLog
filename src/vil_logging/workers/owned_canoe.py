"""Hold process handles for CANoe instances created by this One Click Log run."""

import ctypes
import logging
import os
import threading
import time
from ctypes import wintypes
from pathlib import Path

log = logging.getLogger(__name__)


class OwnedCanoe:
    def __init__(self):
        self.started = time.time()
        self._handles = {}
        self._lock = threading.Lock()
        self._closing = False

    def remember(self, pid):
        import win32api

        if not isinstance(pid, int) or pid <= 0 or pid == os.getpid():
            raise ValueError("Invalid created CANoe PID")
        with self._lock:
            if pid in self._handles:
                return
        handle = win32api.OpenProcess(0x00101001, False, pid)  # SYNCHRONIZE | QUERY_LIMITED_INFORMATION | TERMINATE
        try:
            api = ctypes.WinDLL("kernel32", use_last_error=True)
            api.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD,
                                                       wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
            buffer, length = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
            if not api.QueryFullProcessImageNameW(int(handle), 0, buffer, ctypes.byref(length)):
                raise ctypes.WinError(ctypes.get_last_error())
            # GetProcessTimes via pywin32 constructs datetime objects and imports
            # win32timezone lazily. Native FILETIME avoids that packaging dependency.
            api.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
            times = [wintypes.FILETIME() for _ in range(4)]
            if not api.GetProcessTimes(int(handle), *(ctypes.byref(item) for item in times)):
                raise ctypes.WinError(ctypes.get_last_error())
            created = ((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime) / 10000000 - 11644473600
            if Path(buffer.value).name.casefold() not in {"canoe.exe", "canoe32.exe", "canoe64.exe"} or created < self.started - 1:
                raise ValueError("Refusing a process not created for this One Click Log run")
            with self._lock:
                if self._closing:
                    win32api.TerminateProcess(handle, 0)
                else:
                    self._handles[pid] = handle
                    handle = None
            log.info("canoe.process_owned", extra={"fields": {"pid": pid}})
        finally:
            if handle is not None:
                handle.Close()

    def terminate(self):
        import win32api
        import win32process

        with self._lock:
            self._closing = True
            handles, self._handles = self._handles, {}
        for pid, handle in handles.items():
            try:
                if win32process.GetExitCodeProcess(handle) == 259:
                    win32api.TerminateProcess(handle, 0)
                log.info("canoe.owned_process_termination_sent", extra={"fields": {"pid": pid}})
            except Exception:
                log.exception("canoe.owned_process_close_failed", extra={"fields": {"pid": pid}})
            finally:
                handle.Close()
