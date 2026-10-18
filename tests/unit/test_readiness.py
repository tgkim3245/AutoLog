"""Missing dependencies should guide installation without declaring capture ready."""

import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QFileDialog

from vil_logging.contracts.models import Role
from vil_logging.diagnostics.readiness import INSTALL_URLS, missing_dependencies
from vil_logging.ui.environment_dialog import EnvironmentDialog
from vil_logging.ui.installation_dialog import InstallationDialog, QDesktopServices


def healthy():
    return (
        {"canoe": {"executables": [{"path": "CANoe.exe"}]},
         "dumpcap": {"version_check": {"status": "present"}},
         "capinfos": {"version_check": {"status": "present"}}},
        {"tshark": {"status": "ready"}, "npcap": {"status": "present"}},
    )


def test_optional_tools_are_not_required_for_other_roles():
    environment, connections = healthy()
    environment["canoe"] = {}
    assert missing_dependencies(environment, connections, (Role.ETHERNET,)) == set()
    assert missing_dependencies(environment, {}, (Role.CAN,)) == {"canoe"}
    assert missing_dependencies({}, {}, ()) == set()


@pytest.mark.parametrize("name", ["capinfos", "dumpcap"])
def test_missing_or_broken_companion_tools_require_wireshark_repair(name):
    environment, connections = healthy()
    environment[name]["version_check"]["status"] = "unavailable"
    assert missing_dependencies(environment, connections, (Role.ETHERNET,)) == {"wireshark"}


def test_partial_driver_install_is_not_declared_usable():
    environment, connections = healthy()
    connections["npcap"]["status"] = "unknown"
    assert missing_dependencies(environment, connections, (Role.ETHERNET,)) == {"npcap"}


def test_readiness_missing_buttons_open_installation_and_ignore_unselected_canoe(qtbot):
    dialog = EnvironmentDialog()
    qtbot.addWidget(dialog)
    dialog.set_roles((Role.ETHERNET,))
    dialog.set_report({}, {"tshark": {"status": "missing"}, "npcap": {"status": "missing"}})
    spy = QSignalSpy(dialog.installation_requested)
    dialog.cards["tshark"][3].click()
    dialog.cards["npcap"][3].click()
    assert [spy.at(i)[0] for i in range(spy.count())] == ["wireshark", "npcap"]
    assert dialog.cards["canoe"][1].text() == "선택 대상 아님"
    assert dialog.summary.text() == "4곳 확인 필요"


def test_offline_installer_launch_and_refresh_are_separate(qtbot, monkeypatch, tmp_path):
    dialog = InstallationDialog("npcap")
    qtbot.addWidget(dialog)
    executable = tmp_path / "company approved installer.exe"
    executable.write_bytes(b"test fixture; never execute")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(executable), ""))
    urls = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: urls.append(url) or True)
    refresh = QSignalSpy(dialog.refresh_requested)
    dialog.local_button.click()
    assert urls[0].toLocalFile() == str(executable).replace("\\", "/")
    assert refresh.count() == 0  # Opening an installer does not prove successful installation.
    dialog.refresh_button.click()
    assert refresh.count() == 1


def test_cancel_or_failed_installer_open_does_not_claim_installation(qtbot, monkeypatch, tmp_path):
    dialog = InstallationDialog("wireshark", "en")
    qtbot.addWidget(dialog)
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or False)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: ("", ""))
    dialog.local_button.click()
    assert not opened
    executable = tmp_path / "setup.exe"
    executable.write_bytes(b"test")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(executable), ""))
    dialog.local_button.click()
    assert "Could not open" in dialog.feedback.text()
    dialog.online_button.click()
    assert opened[-1].toString() == INSTALL_URLS["wireshark"]
    assert INSTALL_URLS["wireshark"] in dialog.feedback.text()
