"""Bundled defaults must relocate safely and never override explicit user tools."""

import hashlib
import importlib.util
import io
import logging
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from vil_logging.contracts.models import AppSettings
from vil_logging.diagnostics import capture_tools, connections, environment
from vil_logging.runtime import Runtime
from vil_logging.storage.repository import Repository
from vil_logging.ui.settings_dialog import SettingsDialog

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("autolog_bundle_tests", ROOT / "packaging/wireshark_bundle.py")
bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle)


def test_frozen_bundle_is_relative_to_executable_after_moving(monkeypatch, tmp_path):
    monkeypatch.setattr(capture_tools.sys, "frozen", True, raising=False)
    for folder in (tmp_path / "original", tmp_path / "moved"):
        monkeypatch.setattr(capture_tools.sys, "executable", str(folder / "AutoLog.exe"))
        bundled = folder / "tools/Wireshark/tshark.exe"
        assert capture_tools.bundled_tshark() == bundled
        assert capture_tools.stored_tshark_path(str(bundled)) == ""
        assert capture_tools.tshark_candidates() == [bundled]


def test_default_discovery_and_environment_choose_same_bundled_tool(monkeypatch, tmp_path):
    tool = tmp_path / "tshark.exe"
    tool.write_bytes(b"fixture")
    monkeypatch.setattr(capture_tools, "bundled_tshark", lambda: tool)
    monkeypatch.setattr(environment, "bundled_tshark", lambda: tool)
    version = {"status": "present", "stdout": "TShark (Wireshark) 4.6.9"}
    monkeypatch.setattr(connections, "_version_response", lambda _path: version)
    found = connections._find_tshark("")
    assert found["automatic"] and found["path"] == str(tool)
    assert environment._tool_candidates("tshark") == [tool]
    assert environment._tool_candidates("capinfos")[0] == tmp_path / "capinfos.exe"
    assert capture_tools.tshark_candidates(str(tmp_path / "missing.exe")) == [tmp_path / "missing.exe"]
    assert connections._find_tshark(str(tmp_path / "missing.exe"))["status"] == "invalid"


def test_settings_show_bundled_path_without_persisting_machine_location(qtbot, monkeypatch, tmp_path):
    tool = tmp_path / "tshark.exe"
    tool.write_bytes(b"fixture")
    monkeypatch.setattr(capture_tools, "bundled_tshark", lambda: tool)
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.set_settings(AppSettings(tshark_path=""))
    assert dialog.fields["tshark_path"].text() == str(tool)
    assert dialog._current("tshark_path") == ""
    custom = str(tmp_path / "custom/tshark.exe")
    dialog.fields["tshark_path"].setText(custom)
    assert dialog._current("tshark_path") == custom
    dialog.set_settings(AppSettings(tshark_path=custom))
    assert dialog.fields["tshark_path"].text() == custom


def test_portable_tool_path_does_not_hide_invalid_user_input():
    assert capture_tools.stored_tshark_path("invalid\x00.exe") == "invalid\x00.exe"


def test_upgrade_replaces_only_autolog_managed_tools_with_complete_bundle(monkeypatch, tmp_path):
    root = tmp_path / "bundle"
    root.mkdir()
    for name in ("tshark.exe", "dumpcap.exe", "capinfos.exe"):
        (root / name).write_bytes(b"fixture")
    monkeypatch.setattr(capture_tools, "bundled_tshark", lambda: root / "tshark.exe")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    managed = tmp_path / "VILLogging/tools/Wireshark/tshark.exe"
    assert capture_tools.replaces_legacy_managed_tool(str(managed))
    assert not capture_tools.replaces_legacy_managed_tool(str(tmp_path / "custom/tshark.exe"))
    (root / "dumpcap.exe").unlink()
    assert not capture_tools.replaces_legacy_managed_tool(str(managed))


def test_runtime_upgrade_keeps_recording_settings_while_switching_managed_tool(monkeypatch, tmp_path):
    tool = tmp_path / "tools/Wireshark/tshark.exe"
    tool.parent.mkdir(parents=True)
    for name in ("tshark.exe", "dumpcap.exe", "capinfos.exe"):
        tool.with_name(name).write_bytes(b"fixture")
    monkeypatch.setattr(capture_tools, "bundled_tshark", lambda: tool)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    repo = Repository(tmp_path / "state.sqlite3")
    before = repo.load_settings(str(tmp_path / "captures"))
    repo.save_preferences({"tshark_path": str(tmp_path / "VILLogging/tools/Wireshark/tshark.exe"),
                           "nic_id": "remembered-interface"})
    repo.close()
    runtime = Runtime(tmp_path)
    try:
        runtime.initialize().result(5)
        assert runtime._settings.tshark_path == ""
        assert runtime._settings.nic_id == "remembered-interface"
        assert (runtime._settings.prefix, runtime._settings.next_index, runtime._settings.output_dir) == (
            before.prefix, before.next_index, before.output_dir)
        assert runtime.request_exit().result(5)
    finally:
        runtime.close_for_test()


def item(data):
    return {"name": "vendor.tar.gz", "url": "https://example.invalid/vendor.tar.gz",
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def test_cached_vendor_hash_mismatch_is_rejected_without_redownloading(monkeypatch, tmp_path):
    (tmp_path / "vendor.tar.gz").write_bytes(b"changed")
    network = Mock(side_effect=AssertionError("Do not replace a tampered cache silently"))
    monkeypatch.setattr(bundle.urllib.request, "urlopen", network)
    with pytest.raises(ValueError, match="Cached third-party file has changed"):
        bundle.download(item(b"original"), tmp_path, logging.getLogger(__name__))
    network.assert_not_called()


@pytest.mark.parametrize("received", [b"short", b"incorrect", b"far too much data"])
def test_corrupted_vendor_download_never_becomes_usable_cache(monkeypatch, tmp_path, received):
    monkeypatch.setattr(bundle.urllib.request, "urlopen", lambda *_args, **_kw: io.BytesIO(received))
    with pytest.raises(ValueError):
        bundle.download(item(b"correct!!"), tmp_path, logging.getLogger(__name__))
    assert not list(tmp_path.iterdir())


def test_verified_vendor_cache_is_reused_without_network(monkeypatch, tmp_path):
    data = b"correct"
    target = tmp_path / "vendor.tar.gz"
    target.write_bytes(data)
    monkeypatch.setattr(bundle.urllib.request, "urlopen", Mock(side_effect=AssertionError("offline build")))
    assert bundle.download(item(data), tmp_path, logging.getLogger(__name__)) == target


def test_bundled_tool_smoke_fails_the_release_when_a_dll_cannot_load(monkeypatch, tmp_path):
    monkeypatch.setattr(bundle.subprocess, "run", lambda *_args, **_kw:
                        subprocess.CompletedProcess([], 3221225781, "", "missing runtime"))
    with pytest.raises(RuntimeError, match="did not run correctly"):
        bundle.verify_tools(tmp_path, "4.6.9")
