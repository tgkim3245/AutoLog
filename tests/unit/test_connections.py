import json
import subprocess
from unittest.mock import Mock

import pytest

from vil_logging.diagnostics import connections

GUID_A = "12345678-1234-5678-ABCD-1234567890AB"
GUID_B = "87654321-4321-8765-DCBA-BA0987654321"
GUID_C = "ABCDEF12-3456-7890-ABCD-ABCDEF123456"
NIC_A = "\\Device\\NPF_{" + GUID_A + "}"
NIC_B = "\\Device\\NPF_{" + GUID_B + "}"


def empty_discovery(monkeypatch, tmp_path):
    monkeypatch.setattr(connections, "_windows_interfaces", lambda: ([], ""))
    monkeypatch.setattr(connections, "_discover_npcap", lambda: {"status": "unavailable", "files": []})
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))


def mock_tool(monkeypatch, tmp_path):
    executable = tmp_path / "Wireshark" / "tshark.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"test fixture; never execute")
    monkeypatch.setattr(connections, "_version_response", lambda _: {
        "status": "present", "stdout": "TShark (Wireshark) 4.6.0\nBuilt for tests", "stderr": "",
    })
    return executable


def test_tshark_parser_keeps_unicode_nested_description_and_stable_guid():
    output = (f"1. \\Device\\NPF_{{{GUID_A.lower()}}} (이더넷 (Intel(R) 어댑터))\n"
              f"2. {NIC_A} (duplicate)\n"
              "3. \\Device\\NPF_Loopback (Adapter for loopback traffic capture)\n"
              "4. sshdump (SSH remote capture)\n"
              "Running as user x\n")
    parsed = connections._parse_tshark_interfaces(output)
    assert len(parsed) == 2
    assert parsed[0]["id"] == NIC_A
    assert parsed[0]["description"] == "이더넷 (Intel(R) 어댑터)"
    assert parsed[1]["id"] == "\\Device\\NPF_Loopback"
    assert all(interface["capture_available"] for interface in parsed)


@pytest.mark.parametrize("remembered", [GUID_A.lower(), "{" + GUID_A.lower() + "}", NIC_A.lower()])
def test_friendly_os_name_and_guid_match_capture_and_remembered_nic(monkeypatch, tmp_path, remembered):
    empty_discovery(monkeypatch, tmp_path)
    executable = mock_tool(monkeypatch, tmp_path)
    monkeypatch.setattr(connections, "_windows_interfaces", lambda: ([{
        "id": NIC_A, "name": "이더넷", "description": "Intel(R) Ethernet Controller",
        "status": "up", "mac": "00-11-22-33-44-55", "capture_available": False, "source": "windows",
    }], ""))
    run = Mock(return_value={"success": True, "stdout": f"1. {NIC_A} (장치 설명)\n"})
    monkeypatch.setattr(connections, "_run_query", run)
    report = connections.discover_connections(str(executable), nic_id=remembered)
    interface = report["interfaces"][0]
    assert interface["name"] == "이더넷"
    assert interface["description"] == "Intel(R) Ethernet Controller"
    assert interface["status"] == "up"
    assert interface["mac"] == "00-11-22-33-44-55"
    assert interface["source"] == "tshark"
    assert interface["capture_available"] is True
    assert report["selected_nic_id"] == NIC_A
    assert report["remembered_nic_missing"] is False
    assert report["tshark"]["automatic"] is False
    assert report["tshark"]["status"] == "ready"
    assert report["tshark"]["path"] == str(executable.resolve())
    assert "\n" not in report["tshark"]["version"]
    run.assert_called_once_with([str(executable.resolve()), "-D"], timeout=3)


def test_missing_remembered_nic_never_uses_first_interface(monkeypatch, tmp_path):
    empty_discovery(monkeypatch, tmp_path)
    executable = mock_tool(monkeypatch, tmp_path)
    monkeypatch.setattr(connections, "_run_query", lambda *args, **kwargs: {
        "success": True, "stdout": f"1. {NIC_A} (이더넷)\n2. {NIC_B} (Wi-Fi)\n",
    })
    report = connections.discover_connections(str(executable), nic_id=GUID_C)
    assert len(report["interfaces"]) == 2
    assert report["selected_nic_id"] == ""
    assert report["remembered_nic_missing"] is True
    first_launch = connections.discover_connections(str(executable))
    assert first_launch["selected_nic_id"] == ""
    assert first_launch["remembered_nic_missing"] is False


def test_without_tshark_os_nics_remain_visible_and_not_capture_ready(monkeypatch, tmp_path):
    empty_discovery(monkeypatch, tmp_path)
    windows = [{"id": NIC_A, "name": "이더넷 2", "description": "USB Ethernet",
                "status": "down", "mac": "", "capture_available": False, "source": "windows"}]
    monkeypatch.setattr(connections, "_windows_interfaces", lambda: (windows, ""))
    report = connections.discover_connections(nic_id=NIC_A)
    assert report["tshark"]["status"] == "missing"
    assert report["interfaces"] == windows
    assert report["selected_nic_id"] == NIC_A
    assert report["npcap"]["status"] == "missing"
    assert report["capture_check"] == "not_performed"


def test_explicit_missing_path_is_invalid_and_not_silently_replaced(monkeypatch, tmp_path):
    empty_discovery(monkeypatch, tmp_path)
    missing = tmp_path / "remembered_missing.exe"
    version = Mock(side_effect=AssertionError("Missing executable must not be launched"))
    monkeypatch.setattr(connections, "_version_response", version)
    report = connections.discover_connections(str(missing))
    assert report["tshark"]["status"] == "invalid"
    assert report["tshark"]["path"] == str(missing)
    assert report["tshark"]["automatic"] is False
    assert "직접 선택" in report["tshark"]["message_ko"]
    version.assert_not_called()


def test_wrong_program_version_is_invalid(monkeypatch, tmp_path):
    empty_discovery(monkeypatch, tmp_path)
    executable = mock_tool(monkeypatch, tmp_path)
    monkeypatch.setattr(connections, "_version_response", lambda _: {
        "status": "present", "stdout": "Completely different program 1.0", "stderr": "",
    })
    report = connections.discover_connections(str(executable))
    assert report["tshark"]["status"] == "invalid"
    assert report["interfaces"] == []


def test_blank_or_broken_path_never_falls_back_to_another_installed_tool(monkeypatch, tmp_path):
    empty_discovery(monkeypatch, tmp_path)
    executable = mock_tool(monkeypatch, tmp_path)
    broken = tmp_path / "broken.exe"
    broken.write_bytes(b"test fixture")
    monkeypatch.setattr(connections, "_version_response", lambda path: {
        "status": "unavailable", "original": "DLL missing",
    } if path == broken else {"status": "present", "stdout": "TShark 4.6.0"})
    monkeypatch.setattr(connections, "_run_query", lambda *args, **kwargs: {"success": True, "stdout": ""})
    report = connections.discover_connections()
    assert report["tshark"]["status"] == "missing"
    report = connections.discover_connections(str(broken))
    assert report["tshark"]["status"] == "invalid"
    assert report["tshark"]["path"] != str(executable.resolve())


def test_interface_list_failure_keeps_os_list_and_original_error(monkeypatch, tmp_path):
    empty_discovery(monkeypatch, tmp_path)
    executable = mock_tool(monkeypatch, tmp_path)
    monkeypatch.setattr(connections, "_windows_interfaces", lambda: ([{
        "id": NIC_A, "name": "차량용 이더넷", "description": "USB adapter", "status": "up",
        "mac": "", "source": "windows", "capture_available": False,
    }], ""))
    monkeypatch.setattr(connections, "_run_query", lambda *args, **kwargs: {
        "success": False, "detail": "Npcap service could not be loaded",
    })
    report = connections.discover_connections(str(executable))
    assert report["interfaces"][0]["name"] == "차량용 이더넷"
    assert report["interfaces"][0]["capture_available"] is False
    assert "Npcap service" in report["interface_query_error"]


@pytest.mark.parametrize("failure", [subprocess.TimeoutExpired(["tool", "-D"], 3), OSError("missing DLL")])
def test_query_errors_are_reported_without_raising(monkeypatch, failure):
    monkeypatch.setattr(connections.subprocess, "run", Mock(side_effect=failure))
    report = connections._run_query(["tool.exe", "-D"], timeout=3)
    assert report["success"] is False
    assert report["detail"]
    assert report["reason"] in {"timeout", "execution_failed"}


def test_query_uses_hidden_argument_array_and_timeout(monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr(connections.subprocess, "run", run)
    assert connections._run_query(["tshark.exe", "-D"], timeout=3)["success"] is True
    assert run.call_args.args[0] == ["tshark.exe", "-D"]
    assert run.call_args.kwargs["timeout"] == 3
    assert run.call_args.kwargs.get("shell", False) is False
    if connections.os.name == "nt":
        assert run.call_args.kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW


def test_windows_query_parses_friendly_names_guids_and_link_status(monkeypatch):
    adapters = [
        {"Name": "이더넷", "InterfaceDescription": "Intel(R)", "InterfaceGuid": "{" + GUID_A.lower() + "}",
         "MacAddress": "AA-BB-CC-DD-EE-FF", "Status": "Up"},
        {"Name": "Wi-Fi", "InterfaceDescription": "Wireless", "InterfaceGuid": GUID_B,
         "MacAddress": "", "Status": "Disconnected"},
        {"Name": "No stable GUID", "InterfaceGuid": None},
    ]
    run = Mock(return_value={"success": True, "stdout": "\ufeff" + json.dumps(adapters, ensure_ascii=False)})
    monkeypatch.setattr(connections, "_run_query", run)
    interfaces, error = connections._windows_interfaces()
    assert error == ""
    assert [interface["name"] for interface in interfaces] == ["이더넷", "Wi-Fi"]
    assert [interface["status"] for interface in interfaces] == ["up", "down"]
    assert interfaces[0]["id"] == NIC_A
    assert all(not interface["capture_available"] for interface in interfaces)
    arguments = run.call_args.args[0]
    assert "-NoProfile" in arguments and "-NonInteractive" in arguments
    assert "Get-NetAdapter -ErrorAction Stop" in arguments[-1]
    assert all(command not in arguments[-1] for command in ("Enable-Net", "Disable-Net", "Set-Net", "Restart-Net"))


def test_windows_json_or_query_error_produces_detail(monkeypatch):
    monkeypatch.setattr(connections, "_run_query", lambda *args, **kwargs: {"success": True, "stdout": "garbled"})
    interfaces, error = connections._windows_interfaces()
    assert interfaces == [] and "JSON" in error
    monkeypatch.setattr(connections, "_run_query", lambda *args, **kwargs: {"success": False, "detail": "timed out"})
    interfaces, error = connections._windows_interfaces()
    assert interfaces == [] and error == "timed out"
