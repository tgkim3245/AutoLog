"""Publish only a verified, unchanged, closed file, without replacing a target."""

import errno
import hashlib
import os
import zipfile
from pathlib import Path

from vil_logging.contracts.models import CaptureFilePlan
from vil_logging.storage.blf_snapshot import publication_source
from vil_logging.storage.file_access import ExclusiveFile, matches, observe, plain_path


def cleanup_work_directory(session_dir: Path) -> bool:
    """Remove an empty .vil_work session directory, never deleting its contents."""
    session_dir = Path(session_dir)
    work_root = session_dir.parent
    if work_root.name != ".vil_work" or session_dir.is_symlink() or work_root.is_symlink():
        return False

    removed = False
    try:
        session_dir.rmdir()
    except FileNotFoundError:
        pass
    except OSError as error:
        if error.errno in {errno.EEXIST, errno.ENOTEMPTY}:
            return False
        raise
    else:
        removed = True

    try:
        work_root.rmdir()
    except FileNotFoundError:
        pass
    except OSError as error:
        if error.errno not in {errno.EEXIST, errno.ENOTEMPTY}:
            raise
    else:
        removed = True
    return removed


CHUNK = 1024 * 1024


def uses_zip(file: CaptureFilePlan) -> bool:
    return file.role.value == "ethernet" and file.final_path.name.endswith((".pcap.zip", ".pcapng.zip"))


def zip_work_path(file: CaptureFilePlan) -> Path:
    expected = file.temp_path.with_name(file.temp_path.name + ".zip")
    if not uses_zip(file) or file.final_path.name != expected.name:
        raise ValueError("ZIP does not belong to this Ethernet capture")
    return plain_path(expected)


def capture_source(file: CaptureFilePlan, inspection: dict) -> Path:
    archive = inspection.get("zip_archive")
    if archive:
        expected = zip_work_path(file)
        if plain_path(Path(archive["path"])) != expected or archive["member"] != file.temp_path.name:
            raise ValueError("Unexpected capture ZIP path or member")
        return expected
    return publication_source(file, inspection)


def prepare_capture_zip(file: CaptureFilePlan, inspection: dict, before_publish=None) -> None:
    """Stream, CRC-read and hash-compare a ZIP; retain the raw file until DB commit."""
    if not uses_zip(file) or inspection.get("zip_archive"):
        return
    source, archive = plain_path(file.temp_path), zip_work_path(file)
    expected = {key: inspection[key] for key in ("bytes", "mtime_ns", "inode")}
    created = False
    try:
        with ExclusiveFile(source, expected) as held:
            original = observe(source)
            digest = hashlib.sha256()
            with os.fdopen(os.dup(held.fd), "rb") as reader, archive.open("xb") as writer:
                created = True
                with zipfile.ZipFile(writer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6,
                                     allowZip64=True) as zipped:
                    with zipped.open(source.name, "w", force_zip64=True) as member:
                        size = 0
                        while chunk := reader.read(CHUNK):
                            size += len(chunk)
                            if size > original["bytes"]:
                                raise ValueError("Capture grew during compression")
                            digest.update(chunk)
                            member.write(chunk)
                writer.flush()
                os.fsync(writer.fileno())
            verified, count = hashlib.sha256(), 0
            with zipfile.ZipFile(archive) as zipped:
                if zipped.namelist() != [source.name]:
                    raise ValueError("Unexpected capture ZIP members")
                with zipped.open(source.name) as member:
                    while chunk := member.read(CHUNK):
                        verified.update(chunk)
                        count += len(chunk)
            if count != original["bytes"] or digest.digest() != verified.digest():
                raise ValueError("Capture ZIP content verification failed")
            if not matches(observe(source), original):
                raise ValueError("Capture changed during compression")
        inspection.update(zip_archive={"path": str(archive), "member": source.name,
                                       "source_identity": original, "sha256": digest.hexdigest(),
                                       "source_bytes": count}, **observe(archive))
        if before_publish:
            before_publish(inspection)  # Persist archive identity before the atomic publication.
    except BaseException:
        # Preserve raw data. Remove only an uncommitted ZIP created by this call.
        if created and not inspection.get("zip_archive"):
            archive.unlink(missing_ok=True)
        raise


def cleanup_zip_source(file: CaptureFilePlan, inspection: dict, *, published_path: Path | None = None) -> None:
    archive = inspection.get("zip_archive")
    if not archive:
        return
    capture_source(file, inspection)  # Validate ownership before considering deletion.
    source = plain_path(file.temp_path)
    if not source.exists():
        return
    with ExclusiveFile(published_path or file.final_path, {key: inspection[key] for key in ("bytes", "mtime_ns", "inode")}):
        with ExclusiveFile(source, archive["source_identity"]) as held:
            digest = hashlib.sha256()
            with os.fdopen(os.dup(held.fd), "rb") as reader:
                while chunk := reader.read(CHUNK):
                    digest.update(chunk)
            if digest.hexdigest() != archive["sha256"]:
                raise ValueError("Raw capture changed; source preserved")
            held.delete()


def publish_capture(file: CaptureFilePlan, inspection: dict, before_publish=None) -> Path:
    if file.final_path.exists() or file.final_path.is_symlink():
        raise FileExistsError(f"Existing output is preserved: {file.final_path}")
    prepare_capture_zip(file, inspection, before_publish)
    source, destination = capture_source(file, inspection), file.final_path
    if source.is_symlink():
        raise ValueError("Working capture cannot be a symbolic link")
    current = source.stat()
    expected = (inspection["bytes"], inspection["mtime_ns"], inspection["inode"])
    if (current.st_size, current.st_mtime_ns, current.st_ino) != expected:
        raise ValueError("Working capture changed after inspection")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Existing output is preserved: {destination}")
    if os.name == "nt":
        # Windows rename fails atomically if another program creates the target.
        source.rename(destination)
    else:
        os.link(source, destination)
        source.unlink()
    return destination
