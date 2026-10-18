"""Missing dependencies should guide installation without declaring capture ready."""

import pytest
from PySide6.QtTest import QSignalSpy

from vil_logging.contracts.models import Role
from vil_logging.diagnostics.readiness import missing_dependencies
from vil_logging.ui.environment_dialog import EnvironmentDialog


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


def test_missing_tools_link_to_settings_without_installer_actions(qtbot):
    dialog = EnvironmentDialog()
    qtbot.addWidget(dialog)
    dialog.set_roles((Role.ETHERNET,))
    dialog.set_report({}, {"tshark": {"status": "missing"}, "npcap": {"status": "missing"}})
    spy = QSignalSpy(dialog.settings_requested)
    dialog.cards["tshark"][3].click()
    assert spy.at(0)[0] == "ethernet"
    assert dialog.cards["npcap"][3].isHidden()
    assert dialog.cards["canoe"][1].text() == "선택 대상 아님"
    assert dialog.summary.text() == "4곳 확인 필요"
