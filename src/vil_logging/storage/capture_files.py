"""Publish only a verified, unchanged, closed file, without replacing a target."""

import errno
import os
from pathlib import Path

from vil_logging.contracts.models import CaptureFilePlan
from vil_logging.storage.blf_snapshot import publication_source


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


def publish_capture(file: CaptureFilePlan, inspection: dict) -> Path:
    source, destination = publication_source(file, inspection), file.final_path
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
