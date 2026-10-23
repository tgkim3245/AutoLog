"""Broken multi-version COM registration: diagnosis only, no registry writes/activation."""

import pytest

from vil_logging.adapters.canoe import CanoeCapture, _create_application
from vil_logging.diagnostics import canoe_setup, environment

CLSID = "{12345678-1234-1234-1234-123456789ABC}"
PROGID_KEY = r"CANoe.Application\CLSID"
SERVER_KEY = rf"CLSID\{CLSID}\LocalServer32"


@pytest.fixture
def registry(tmp_path, monkeypatch):
    import winreg

    exe = tmp_path / "Vector CANoe 19" / "Exec64" / "CANoe64.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"fixture, never executed")
    tool = exe.with_name("RegisterComponents.exe")
    tool.write_bytes(b"fixture, never executed")
    keys = {PROGID_KEY: CLSID, SERVER_KEY: f'"{exe}" /automation'}

    class Key:
        def __init__(self, name):
            self.name = name

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    def open_key(_root, name, *_args):
        if name not in keys:
            raise FileNotFoundError(name)
        return Key(name)

    monkeypatch.setattr(winreg, "OpenKey", open_key)
    monkeypatch.setattr(winreg, "QueryValueEx", lambda key, name: (keys[key.name], winreg.REG_SZ))
    monkeypatch.setattr(environment, "_discover_canoe", lambda: {
        "executables": [{"path": str(exe), "version_check": {"file_version": "19.3.118"}}]})
    return keys, exe, tool


def test_registered_server_with_spaces_and_arguments_is_resolved(registry):
    _keys, exe, _tool = registry
    assert canoe_setup.registered_executable() == exe


@pytest.mark.parametrize("damage", ["missing_progid", "empty_clsid", "invalid_clsid", "missing_server",
                                   "missing_exe", "empty_command", "non_string", "other_exe"])
def test_missing_and_stale_registration_are_actionable_without_launching_or_writing(registry, monkeypatch, damage):
    import win32com.client

    keys, exe, tool = registry
    if damage == "missing_progid":
        del keys[PROGID_KEY]
    elif damage in {"empty_clsid", "invalid_clsid"}:
        keys[PROGID_KEY] = "" if damage == "empty_clsid" else "invalid"
    elif damage == "missing_server":
        del keys[SERVER_KEY]
    elif damage == "missing_exe":
        keys[SERVER_KEY] = str(exe.parent / "removed" / "CANoe64.exe")
    elif damage in {"empty_command", "non_string"}:
        keys[SERVER_KEY] = "" if damage == "empty_command" else 42
    else:
        other = exe.with_name("Other.exe")
        other.write_bytes(b"never executed")
        keys[SERVER_KEY] = str(other)
    before = dict(keys)
    activated = []
    monkeypatch.setattr(win32com.client, "DispatchEx", lambda *args: activated.append(args))
    with pytest.raises(canoe_setup.CanoeActivationError) as failure:
        _create_application()
    error = failure.value
    assert error.connection_issue == ("com_registration_missing" if damage == "missing_progid" else "com_registration_invalid")
    assert error.settings_path == "" and error.process_ids == []
    assert error.diagnostics["registry_key"] in {PROGID_KEY, SERVER_KEY}
    assert not error.diagnostics["registry_modified"]
    assert error.diagnostics["repair_tools"][0]["registration_tool"] == str(tool)
    assert "RegisterComponents.exe" in str(error) and "administrator" in str(error)
    assert not activated and keys == before
    assert exe.read_bytes() == b"fixture, never executed"
    assert tool.read_bytes() == b"fixture, never executed"


def test_permissions_are_not_misreported_as_missing_registration(monkeypatch):
    import winreg

    def denied(*_args):
        raise PermissionError("Registry permission denied")

    monkeypatch.setattr(winreg, "OpenKey", denied)
    with pytest.raises(canoe_setup.CanoeActivationError) as failure:
        canoe_setup.ensure_independent_activation()
    assert failure.value.connection_issue == "setup_failed"
    assert "permission denied" in str(failure.value)


def test_failed_activation_preserves_diagnostics_and_avoids_none_object_noise(tmp_path):
    cfg = tmp_path / "CAN.cfg"
    cfg.write_bytes(b"untouched")
    diagnostics = {"registry_key": PROGID_KEY, "registry_modified": False}
    error = canoe_setup.CanoeActivationError("com_registration_missing", "Missing COM", diagnostics=diagnostics)

    def fail():
        raise error

    capture = CanoeCapture(create_application=fail)
    with pytest.raises(canoe_setup.CanoeActivationError):
        capture.connect({"cfg_path": str(cfg)})
    capture.record_failure("connect", error)
    assert capture.journal[-2]["registration_diagnostics"] == diagnostics
    assert capture.journal[-1]["observed"] == {"application_created": False}
    assert cfg.read_bytes() == b"untouched"
