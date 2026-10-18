import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

from vil_logging.diagnostics import environment


def configure_empty_environment(monkeypatch, tmp_path):
    program_files = tmp_path / "programs"
    program_files.mkdir()
    monkeypatch.setenv("ProgramFiles", str(program_files))
    monkeypatch.setenv("ProgramFiles(x86)", str(program_files))
    monkeypatch.setenv("SystemRoot", str(tmp_path / "Windows"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(environment.shutil, "which", lambda _: None)
    monkeypatch.setattr(environment, "_canoe_registration", lambda: {"status": "unavailable", "entries": []})
    return program_files


def test_missing_tools_are_bounded_discovery_not_capture_failure(monkeypatch, tmp_path):
    configure_empty_environment(monkeypatch, tmp_path)
    run = Mock(side_effect=AssertionError("No version command should run without an executable"))
    monkeypatch.setattr(environment.subprocess, "run", run)
    report = environment.collect_environment()
    assert report["tshark"]["status"] == "unavailable"
    assert report["canoe"]["status"] == "unavailable"
    assert report["npcap"]["status"] == "unavailable"
    assert report["tshark"]["capture_check"] == "not_performed"
    assert report["hardware_checks"] == "not_performed"
    assert report["network_access"] == "not_used"
    assert report["python"]["pointer_bits"] in (32, 64)
    json.dumps(report)
    run.assert_not_called()


def test_present_executable_and_version_do_not_claim_live_capture(monkeypatch, tmp_path):
    program_files = configure_empty_environment(monkeypatch, tmp_path)
    wireshark = program_files / "Wireshark"
    wireshark.mkdir()
    for name in ("tshark", "dumpcap", "capinfos"):
        (wireshark / f"{name}.exe").write_bytes(b"fake executable; never executed")
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "TShark test version\n", ""))
    monkeypatch.setattr(environment.subprocess, "run", run)
    report = environment.collect_environment(str(wireshark / "tshark.exe"))
    assert report["tshark"]["status"] == "present"
    assert report["tshark"]["version_check"]["status"] == "present"
    assert report["tshark"]["capture_check"] == "not_performed"
    assert run.call_count == 3
    for call in run.call_args_list:
        assert isinstance(call.args[0], list)
        assert call.args[0][1:] == ["--version"]
        assert call.kwargs["timeout"] == 3
        assert call.kwargs.get("shell", False) is False
        if environment.os.name == "nt":
            assert call.kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW


def test_explicit_missing_tshark_never_substitutes_path_executable(monkeypatch, tmp_path):
    configure_empty_environment(monkeypatch, tmp_path)
    other = tmp_path / "other_tshark.exe"
    other.write_bytes(b"fake")
    monkeypatch.setattr(environment.shutil, "which", lambda _: str(other))
    monkeypatch.setattr(environment.subprocess, "run",
                        Mock(return_value=subprocess.CompletedProcess([], 0, "version", "")))
    specified = tmp_path / "user_selected_missing.exe"
    report = environment.collect_environment(str(specified))
    assert report["tshark"]["status"] == "unavailable"
    assert report["tshark"]["checked_paths"] == [str(specified)]
    assert report["tshark"]["path"] == ""


def test_version_timeout_preserves_partial_output_and_presence(monkeypatch, tmp_path):
    configure_empty_environment(monkeypatch, tmp_path)
    executable = tmp_path / "tshark.exe"
    executable.write_bytes(b"fake")
    run = Mock(side_effect=subprocess.TimeoutExpired([str(executable), "--version"], 3,
                                                    output=b"partial version", stderr=b"partial warning"))
    monkeypatch.setattr(environment.subprocess, "run", run)
    report = environment.collect_environment(str(executable))
    assert report["tshark"]["status"] == "present"
    version = report["tshark"]["version_check"]
    assert version["status"] == "unknown"
    assert version["reason"] == "timeout"
    assert version["stdout"] == "partial version"
    assert version["stderr"] == "partial warning"
    json.dumps(report)


def test_tool_execution_error_is_separate_from_file_presence(monkeypatch, tmp_path):
    configure_empty_environment(monkeypatch, tmp_path)
    executable = tmp_path / "tshark.exe"
    executable.write_bytes(b"fake")
    monkeypatch.setattr(environment.subprocess, "run", Mock(side_effect=OSError("missing runtime DLL")))
    report = environment.collect_environment(str(executable))
    assert report["tshark"]["status"] == "present"
    assert report["tshark"]["version_check"]["status"] == "unavailable"
    assert "missing runtime DLL" in report["tshark"]["version_check"]["original"]


def test_canoe_and_driver_presence_do_not_claim_license_or_device_access(monkeypatch, tmp_path):
    program_files = configure_empty_environment(monkeypatch, tmp_path)
    executable = program_files / "Vector CANoe 19" / "Exec64" / "CANoe64.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"fake")
    driver = Path(environment.os.environ["SystemRoot"]) / "System32" / "drivers" / "npcap.sys"
    driver.parent.mkdir(parents=True)
    driver.write_bytes(b"fake driver")
    monkeypatch.setattr(environment, "_file_version", lambda _: {"status": "present", "file_version": "19.3.118"})
    monkeypatch.setattr(environment, "_canoe_registration", lambda: {
        "status": "present", "entries": [{"progid": "CANoe.Application", "clsid": "fake-clsid"}],
        "activation_check": "not_performed",
    })
    report = environment.collect_environment()
    assert report["canoe"]["status"] == "present"
    assert report["canoe"]["license_check"] == "not_performed"
    assert report["canoe"]["com_activation_check"] == "not_performed"
    assert report["canoe"]["measurement_check"] == "not_performed"
    assert report["canoe"]["independent_instances_check"] == "not_performed"
    assert report["npcap"]["status"] == "present"
    assert report["npcap"]["driver_loaded_check"] == "not_performed"
    assert report["npcap"]["nic_access_check"] == "not_performed"
