"""Explicit setup preserves every other byte and never edits a running CANoe installation."""

from pathlib import Path

import pytest

from vil_logging.diagnostics import canoe_setup


@pytest.fixture
def settings(tmp_path, monkeypatch):
    path = tmp_path / "can.ini"
    original = b"; Vector comment\r\n[System]\r\nSingleCOMClient = 0\r\nOther=unchanged\r\n"
    path.write_bytes(original)
    monkeypatch.setattr(canoe_setup, "canoe_process_ids", lambda: [])
    return path, original


def test_explicit_setup_backs_up_original_and_changes_only_the_flag(settings):
    path, original = settings
    result = canoe_setup.set_single_client(path, True, expected=original)
    assert result["changed"] and result["enabled"]
    assert Path(result["backup"]).read_bytes() == original
    assert path.read_bytes() == original.replace(b" = 0", b" = 1")
    assert canoe_setup.single_client_enabled(path)
    enabled = path.read_bytes()
    canoe_setup.set_single_client(path, False, expected=enabled)
    assert path.read_bytes() == original
    assert not canoe_setup.single_client_enabled(path)


def test_running_canoe_prevents_any_setup_write(settings, monkeypatch):
    path, original = settings
    monkeypatch.setattr(canoe_setup, "canoe_process_ids", lambda: [123])
    with pytest.raises(RuntimeError, match="Close all"):
        canoe_setup.set_single_client(path, True, expected=original)
    assert path.read_bytes() == original and not list(path.parent.glob("*.bak"))


def test_concurrent_setting_edit_is_preserved(settings):
    path, original = settings
    changed = original + b"UserSetting=preserve\r\n"
    path.write_bytes(changed)
    with pytest.raises(RuntimeError, match="changed since"):
        canoe_setup.set_single_client(path, True, expected=original)
    assert path.read_bytes() == changed and not list(path.parent.glob("*.bak"))


def test_canoe_starting_during_setup_preserves_ini(settings, monkeypatch):
    path, original = settings
    states = iter([[], [123]])
    monkeypatch.setattr(canoe_setup, "canoe_process_ids", lambda: next(states))
    with pytest.raises(RuntimeError, match="started during"):
        canoe_setup.set_single_client(path, True, expected=original)
    assert path.read_bytes() == original


def test_ambiguous_setting_is_never_rewritten(settings):
    path, original = settings
    original += b"SingleCOMClient=0\r\n"
    path.write_bytes(original)
    with pytest.raises(ValueError, match="exactly one"):
        canoe_setup.set_single_client(path, True, expected=original)
    assert path.read_bytes() == original
