"""Windows exclusive handles: validate and mutate the same opened file.

No forced unlock, attribute change, overwrite, or process termination is used.
"""

import ctypes
import os
import stat
from ctypes import wintypes
from pathlib import Path


def identity(info: os.stat_result) -> dict:
    return {"device": info.st_dev, "inode": info.st_ino,
            "bytes": info.st_size, "mtime_ns": info.st_mtime_ns}


def matches(actual: dict, expected: dict) -> bool:
    return bool(expected.get("inode")) and all(actual.get(key) == value
                                               for key, value in expected.items())


def plain_path(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError(f"Links and junctions cannot be managed: {part}")
    return path


def observe(path: Path) -> dict:
    info = plain_path(path).lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError(f"Only a regular file with one link can be managed: {path}")
    return identity(info)


class ExclusiveFile:
    """Hold share-mode zero until the requested rename or deletion is finished."""

    def __init__(self, path: Path, expected: dict):
        if os.name != "nt":
            raise OSError("File management requires Windows")
        import msvcrt

        self.path = plain_path(path)
        self.fd = None
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                         wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                         wintypes.HANDLE)
        self.api.CreateFileW.restype = wintypes.HANDLE
        self.api.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.api.SetFileInformationByHandle.argtypes = (wintypes.HANDLE, ctypes.c_int,
                                                       wintypes.LPVOID, wintypes.DWORD)
        self.api.SetFileInformationByHandle.restype = wintypes.BOOL
        # DELETE | GENERIC_READ; no sharing; OPEN_EXISTING; OPEN_REPARSE_POINT.
        handle = self.api.CreateFileW(str(self.path), 0x80010000, 0, None, 3, 0x00200000, None)
        if handle == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            self.fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            self.api.CloseHandle(handle)
            raise
        try:
            info = os.fstat(self.fd)
            self.identity = identity(info)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or getattr(info, "st_file_attributes", 0) & 0x400
                    or not matches(self.identity, expected)):
                raise ValueError(f"File identity or content changed: {self.path}")
        except BaseException:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def _set(self, kind: int, data):
        import msvcrt

        if not self.api.SetFileInformationByHandle(msvcrt.get_osfhandle(self.fd), kind,
                                                   ctypes.byref(data), ctypes.sizeof(data)):
            raise ctypes.WinError(ctypes.get_last_error())

    def rename(self, destination: Path):
        destination = plain_path(destination)
        if destination.parent != self.path.parent:
            raise ValueError("A prefix change must keep the same directory")
        self.move(destination)

    def move(self, destination: Path):
        """Move this exact open file without replacement (same volume only)."""
        destination = plain_path(destination)

        class RenameInfo(ctypes.Structure):
            _fields_ = [("Flags", wintypes.DWORD), ("RootDirectory", wintypes.HANDLE),
                        ("FileNameLength", wintypes.DWORD), ("FileName", wintypes.WCHAR * 1)]

        encoded = str(destination).encode("utf-16-le")
        size = max(ctypes.sizeof(RenameInfo), RenameInfo.FileName.offset + len(encoded) + 2)
        buffer = ctypes.create_string_buffer(size)
        header = RenameInfo.from_buffer(buffer)
        header.Flags = 0  # ReplaceIfExists = FALSE, including a late collision.
        header.FileNameLength = len(encoded)
        ctypes.memmove(ctypes.addressof(buffer) + RenameInfo.FileName.offset, encoded, len(encoded))
        self._set(3, buffer)

    def delete(self):
        # Windows removes the marked file when this exclusive handle closes.
        self._set(4, wintypes.BOOL(True))
