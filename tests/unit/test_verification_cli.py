"""Verification must use the explicitly selected tool, with no hidden discovery."""

import pytest

from vil_logging.app import main


@pytest.mark.parametrize("flag,module,name", [
    ("--verify-ethernet", "vil_logging.verification", "verify_ethernet"),
    ("--verify-monitoring", "vil_logging.verification", "verify_monitoring"),
    ("--verify-recovery", "vil_logging.verification", "verify_recovery"),
    ("--verify-load", "vil_logging.diagnostics.load_test", "verify_load"),
])
def test_verification_requires_and_forwards_manual_tool_path(monkeypatch, tmp_path, flag, module, name):
    import importlib
    with pytest.raises(SystemExit) as error:
        main([flag, "--data-dir", str(tmp_path)])
    assert error.value.code == 2
    calls = []

    def verify(folder, **kwargs):
        calls.append((folder, kwargs))
        return {"passed": True}

    monkeypatch.setattr(importlib.import_module(module), name, verify)
    assert main([flag, "--data-dir", str(tmp_path), "--tshark", "C:/Selected/tshark.exe"]) == 0
    assert calls[0][0] == tmp_path
    assert calls[0][1]["tshark_path"] == "C:/Selected/tshark.exe"
