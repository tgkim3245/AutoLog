"""Real Windows retained handles, stable snapshots and conservative cleanup."""

import struct
from dataclasses import replace

import pytest

from vil_logging.contracts.models import CaptureFilePlan, Role
from vil_logging.storage.blf import FILE_HEADER
from vil_logging.storage.blf_snapshot import (
    cleanup_finalization_files,
    cleanup_retained_source,
    publication_source,
    seal_blf,
    snapshot_path,
)
from vil_logging.storage.capture_files import publish_capture
from vil_logging.storage.file_access import observe


@pytest.fixture
def capture(tmp_path):
    source = tmp_path / ".vil_work" / "test-session" / "arbitrary_17.blf"
    source.parent.mkdir(parents=True)
    source.write_bytes(FILE_HEADER.pack(b"LOGG", 144, *([0] * 8), 144, 144, 0, 0, *([0] * 16)).ljust(144, b"\0"))
    return CaptureFilePlan(Role.CAN, source.name, source, tmp_path / source.name)


@pytest.mark.parametrize("access", ["rb", "r+b"])
def test_complete_snapshot_publishes_while_producer_retains_handle_then_cleans(capture, access):
    original = capture.temp_path.read_bytes()
    with capture.temp_path.open(access):
        checked = seal_blf(capture.temp_path)
        assert checked["object_count"] == 0
        assert publish_capture(capture, checked) == capture.final_path
        assert capture.final_path.read_bytes() == original == capture.temp_path.read_bytes()
        with pytest.raises(OSError):
            cleanup_retained_source(capture, checked)
    assert cleanup_retained_source(capture, checked)
    assert not capture.temp_path.exists() and capture.final_path.read_bytes() == original


@pytest.mark.parametrize("fault", ["unfinalized", "copy_collision", "target_collision", "wrong_path", "wrong_role"])
def test_invalid_snapshot_and_existing_or_unrelated_paths_are_preserved(capture, fault):
    original = capture.temp_path.read_bytes()
    if fault == "unfinalized":
        data = bytearray(original)
        struct.pack_into("<Q", data, 16, 0)
        capture.temp_path.write_bytes(data)
        with pytest.raises(ValueError, match="not finalized"):
            seal_blf(capture.temp_path)
        assert not snapshot_path(capture.temp_path).exists()
        return
    if fault == "copy_collision":
        snapshot_path(capture.temp_path).write_bytes(b"preserve")
        with pytest.raises(FileExistsError):
            seal_blf(capture.temp_path)
        assert snapshot_path(capture.temp_path).read_bytes() == b"preserve"
        return
    checked = seal_blf(capture.temp_path)
    if fault == "target_collision":
        capture.final_path.write_bytes(b"preserve")
        with pytest.raises(FileExistsError):
            publish_capture(capture, checked)
        assert capture.final_path.read_bytes() == b"preserve"
    else:
        if fault == "wrong_path":
            checked["blf_snapshot_path"] = str(capture.final_path)
        else:
            capture = replace(capture, role=Role.ETHERNET)
        with pytest.raises(ValueError, match="does not belong"):
            publication_source(capture, checked)
    assert capture.temp_path.read_bytes() == original


@pytest.mark.parametrize("fault", ["source_changed", "archive_changed", "archive_missing"])
def test_cleanup_preserves_source_if_either_copy_is_unconfirmed(capture, fault):
    checked = seal_blf(capture.temp_path)
    publish_capture(capture, checked)
    if fault == "source_changed":
        with capture.temp_path.open("r+b") as writer:
            writer.seek(100)
            writer.write(b"x")
    elif fault == "archive_changed":
        capture.final_path.write_bytes(b"changed")
    else:
        capture.final_path.unlink()
    with pytest.raises((OSError, ValueError)):
        cleanup_retained_source(capture, checked)
    assert capture.temp_path.is_file()


def test_source_change_during_snapshot_is_rejected(capture, monkeypatch):
    from pathlib import Path
    original_open = Path.open

    class MutatingWriter:
        def __init__(self, handle):
            self.handle = handle
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.handle.close()
        def __getattr__(self, name):
            return getattr(self.handle, name)
        def write(self, data):
            result = self.handle.write(data)
            with original_open(capture.temp_path, "r+b") as writer:
                writer.seek(100)
                writer.write(b"x")
            return result

    def intercept(path, mode="r", *args, **kwargs):
        result = original_open(path, mode, *args, **kwargs)
        return MutatingWriter(result) if path == snapshot_path(capture.temp_path) and mode == "xb" else result

    monkeypatch.setattr(Path, "open", intercept)
    with pytest.raises(ValueError, match="changed"):
        seal_blf(capture.temp_path)
    assert capture.temp_path.exists() and not snapshot_path(capture.temp_path).exists()


@pytest.mark.parametrize("fault", ["locked", "wrong_name", "wrong_parent", "replaced", "archive_missing"])
def test_disposable_finalization_files_are_cleaned_only_with_exact_ownership(capture, fault):
    from uuid import uuid4

    checked = seal_blf(capture.temp_path)
    publish_capture(capture, checked)
    path = capture.temp_path.parent / (".AutoLog_finalize_" + uuid4().hex + ".blf")
    if fault == "wrong_name":
        path = path.with_name("user_recording.blf")
    elif fault == "wrong_parent":
        path = path.parent.parent / path.name
    path.write_bytes(b"owned disposable output")
    checked["finalization_files"] = [{"path": str(path), "identity": observe(path)}]
    if fault == "replaced":
        path.unlink()
        path.write_bytes(b"foreign replacement")
    elif fault == "archive_missing":
        capture.final_path.unlink()
    if fault == "locked":
        with path.open("rb"):
            result = cleanup_finalization_files(capture, checked)
            assert path.exists() and not result[0].get("cleaned")
        assert cleanup_finalization_files(capture, checked)[0]["cleaned"] and not path.exists()
    else:
        with pytest.raises((ValueError, OSError)):
            cleanup_finalization_files(capture, checked)
        assert path.exists()
