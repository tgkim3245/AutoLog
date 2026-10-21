"""Seal a stopped BLF without requiring its producer to release every handle.

The caller must first confirm its own logging trigger is inactive. A retained
writer is never unlocked or deleted. Only a complete, unchanged copy is sealed.
"""

import hashlib
import os
import time
from pathlib import Path

from vil_logging.storage.blf import CHUNK, inspect_blf
from vil_logging.storage.file_access import ExclusiveFile, identity, matches, observe, plain_path


def snapshot_path(source: Path) -> Path:
    return Path(source).with_name(Path(source).name + ".sealed")


def _digest(stream):
    result = hashlib.sha256()
    while chunk := stream.read(CHUNK):
        result.update(chunk)
    return result.hexdigest()


def seal_blf(source: Path) -> dict:
    """Copy, compare a second source read, and validate all BLF containers."""
    source = plain_path(source)
    before = observe(source)
    destination = snapshot_path(source)
    created = False
    deadline = time.monotonic() + 110
    try:
        with source.open("rb") as reader, destination.open("xb") as writer:
            created = True
            if not matches(identity(os.fstat(reader.fileno())), before):
                raise ValueError("BLF source changed before snapshot")
            digest = hashlib.sha256()
            while chunk := reader.read(CHUNK):
                if time.monotonic() > deadline or writer.tell() + len(chunk) > before["bytes"]:
                    raise ValueError("BLF source is still growing or snapshot exceeded its time limit")
                writer.write(chunk)
                digest.update(chunk)
            writer.flush()
            os.fsync(writer.fileno())
            if writer.tell() != before["bytes"]:
                raise ValueError("BLF source size changed during snapshot")
            reader.seek(0)
            check = hashlib.sha256()
            while chunk := reader.read(CHUNK):
                if time.monotonic() > deadline or reader.tell() > before["bytes"]:
                    raise ValueError("BLF source changed or snapshot exceeded its time limit")
                check.update(chunk)
            if digest.digest() != check.digest() or not matches(identity(os.fstat(reader.fileno())), before):
                raise ValueError("BLF source changed during snapshot")
        if not matches(observe(source), before):
            raise ValueError("BLF source changed after snapshot")
        inspection = inspect_blf(destination, timeout=max(1, deadline - time.monotonic()))
        return {**inspection, "blf_snapshot_path": str(destination),
                "retained_source": {"path": str(source), "identity": before, "sha256": digest.hexdigest()},
                "closure_evidence": "inactive_trigger_and_complete_stable_snapshot"}
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)  # Only the copy created by this call.
        raise


def publication_source(file, inspection):
    """Never trust an arbitrary snapshot path received from a worker/journal."""
    claimed = inspection.get("blf_snapshot_path")
    if not claimed:
        return plain_path(file.temp_path)
    expected = plain_path(snapshot_path(file.temp_path))
    retained = inspection.get("retained_source", {})
    if (file.role.value not in {"can", "diag"} or file.temp_path.suffix.lower() != ".blf"
            or plain_path(Path(claimed)) != expected
            or plain_path(Path(retained.get("path", ""))) != plain_path(file.temp_path)):
        raise ValueError("Snapshot does not belong to this BLF capture")
    return expected


def cleanup_retained_source(file, inspection) -> bool:
    """Delete only an unlocked, byte-identical source of a verified archive."""
    retained = inspection.get("retained_source")
    if not retained:
        return True
    publication_source(file, inspection)
    source = plain_path(file.temp_path)
    if not source.exists():
        return True
    before = observe(source)
    expected = retained["identity"]
    if any(before[key] != expected[key] for key in ("device", "inode", "bytes")):
        raise ValueError("Retained BLF identity changed; preserve the source")
    with ExclusiveFile(source, before) as opened:
        with ExclusiveFile(file.final_path, {key: inspection[key] for key in ("inode", "bytes", "mtime_ns")}):
            # Last-write time can be committed only when CANoe closes its handle.
            # A matching inode/size and full content hash establish the same data.
            with os.fdopen(os.dup(opened.fd), "rb") as reader:
                if _digest(reader) != retained["sha256"]:
                    raise ValueError("Retained BLF contents changed; preserve the source")
            opened.delete()
    return True
