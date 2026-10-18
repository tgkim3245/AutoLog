"""Stream BLF structure/compressed containers; never retain frame contents.

Checks structural readability, not signal semantics or expected vehicle traffic.
Unknown record types are counted and skipped using their declared object sizes.
"""

import os
import struct
import time
import zlib
from collections import Counter
from pathlib import Path

FILE_HEADER = struct.Struct("<4sI8BQQII16H")
OBJECT_HEADER = struct.Struct("<4sHHII")
CHUNK = 256 * 1024


class ObjectScanner:
    def __init__(self):
        self.pending = bytearray()
        self.remaining = 0
        self.counts = Counter()

    def feed(self, chunk):
        self.pending.extend(chunk)
        while self.pending:
            if self.remaining:
                taken = min(self.remaining, len(self.pending))
                del self.pending[:taken]
                self.remaining -= taken
                if self.remaining or not self.pending:
                    return
            # Alignment bytes may straddle two compressed containers.
            if self.pending[0] == 0:
                padding = 0
                while padding < len(self.pending) and self.pending[padding] == 0:
                    padding += 1
                if padding > 3:
                    raise ValueError("Unexpected BLF object padding")
                if padding == len(self.pending):
                    return
                del self.pending[:padding]
            if len(self.pending) < OBJECT_HEADER.size:
                return
            signature, header_size, version, size, kind = OBJECT_HEADER.unpack_from(self.pending)
            if signature != b"LOBJ" or not OBJECT_HEADER.size <= header_size <= size:
                raise ValueError("Invalid BLF record header / incomplete object stream")
            if version not in {1, 2, 3}:
                raise ValueError(f"Unsupported BLF record header version: {version}")
            if kind not in self.counts and len(self.counts) >= 256:
                raise ValueError("Too many distinct BLF record types")
            self.counts[kind] += 1
            del self.pending[:OBJECT_HEADER.size]
            self.remaining = size - OBJECT_HEADER.size

    def finish(self):
        if self.remaining or any(self.pending) or len(self.pending) > 3:
            raise ValueError("Truncated BLF record at end of file")


def inspect_blf(path: Path, *, timeout: float = 110) -> dict:
    path = Path(path)
    before = path.stat()
    deadline = time.monotonic() + timeout
    scanner = ObjectScanner()
    containers = expanded_total = 0
    with path.open("rb") as source:
        header = source.read(FILE_HEADER.size)
        if len(header) != FILE_HEADER.size:
            raise ValueError("Incomplete BLF file header")
        values = FILE_HEADER.unpack(header)
        if values[0] != b"LOGG" or not FILE_HEADER.size <= values[1] <= before.st_size:
            raise ValueError("Not a supported BLF file")
        if values[10] != before.st_size:
            raise ValueError("BLF final file size does not match its header; not finalized")
        declared_objects = values[12]
        source.seek(values[1])
        while source.tell() < before.st_size:
            if time.monotonic() > deadline:
                raise TimeoutError("BLF inspection exceeded its time limit")
            # Both padding conventions seen in BLF producers fit 0..3 zero bytes.
            prefix = source.read(4)
            padding = 0
            while prefix[:1] == b"\x00" and padding < 3:
                prefix = prefix[1:] + source.read(1)
                padding += 1
            if not prefix.strip(b"\x00") and source.tell() == before.st_size:
                break
            rest = source.read(OBJECT_HEADER.size - 4)
            if len(prefix + rest) != OBJECT_HEADER.size:
                raise ValueError("Truncated BLF container header")
            signature, header_size, _version, size, kind = OBJECT_HEADER.unpack(prefix + rest)
            if signature != b"LOBJ" or not OBJECT_HEADER.size <= header_size <= size:
                raise ValueError("Invalid BLF container / top-level object")
            remaining = size - OBJECT_HEADER.size
            if remaining > before.st_size - source.tell():
                raise ValueError("Truncated BLF container")
            if kind != 10:
                if kind not in scanner.counts and len(scanner.counts) >= 256:
                    raise ValueError("Too many distinct BLF record types")
                scanner.counts[kind] += 1
                source.seek(remaining, os.SEEK_CUR)
                continue
            if header_size != OBJECT_HEADER.size or remaining < 16:
                raise ValueError("Unsupported BLF container header")
            method, expected = struct.unpack("<H6xI4x", source.read(16))
            remaining -= 16
            if method not in {0, 2}:
                raise ValueError(f"Unsupported BLF compression method: {method}")
            inflater = zlib.decompressobj() if method == 2 else None
            expanded = 0
            while remaining:
                if time.monotonic() > deadline:
                    raise TimeoutError("BLF inspection exceeded its time limit")
                chunk = source.read(min(CHUNK, remaining))
                if not chunk:
                    raise ValueError("Truncated BLF compressed data")
                remaining -= len(chunk)
                if inflater:
                    while chunk:
                        decoded = inflater.decompress(chunk, CHUNK)
                        expanded += len(decoded)
                        if expanded > expected:
                            raise ValueError("BLF expanded data exceeds its declared size")
                        scanner.feed(decoded)
                        chunk = inflater.unconsumed_tail
                    if inflater.unused_data:
                        raise ValueError("Trailing data inside BLF compressed stream")
                else:
                    expanded += len(chunk)
                    scanner.feed(chunk)
            if (inflater and not inflater.eof) or expanded != expected:
                raise ValueError("BLF compressed stream is incomplete or has the wrong length")
            containers += 1
            expanded_total += expanded
        scanner.finish()
        after = os.fstat(source.fileno())
    actual_count = sum(scanner.counts.values())
    # Vector files may omit restore-point/other metadata records from this count.
    # All physical record boundaries are checked; a larger header count is incomplete.
    if declared_objects > actual_count:
        raise ValueError(f"BLF objects missing: header={declared_objects}, read={actual_count}")
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError("BLF changed during inspection")
    return {"actual_format": "blf", "bytes": after.st_size, "mtime_ns": after.st_mtime_ns,
            "inode": after.st_ino, "object_count": actual_count, "containers": containers,
            "declared_object_count": declared_objects, "header_count_matches": declared_objects == actual_count,
            "expanded_bytes": expanded_total, "object_types": dict(scanner.counts),
            "validation_scope": "BLF headers, compressed-stream integrity, record boundaries and counts; no signal decoding"}
