"""Missing dependencies should guide installation without declaring capture ready."""

import pytest

from vil_logging.contracts.models import Role
from vil_logging.diagnostics.readiness import missing_dependencies


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
