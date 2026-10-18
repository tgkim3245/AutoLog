"""Dependency checks for the selected targets; file presence is not live readiness."""

from vil_logging.contracts.models import Role


def missing_dependencies(environment: dict, connections: dict, roles: tuple[Role, ...]) -> set[str]:
    missing = set()
    if Role.CAN in roles or Role.DIAG in roles:
        if not environment.get("canoe", {}).get("executables"):
            missing.add("canoe")
    if Role.ETHERNET in roles:
        if connections.get("tshark", {}).get("status") != "ready":
            missing.add("wireshark")
        for name in ("capinfos", "dumpcap"):
            if environment.get(name, {}).get("version_check", {}).get("status") != "present":
                missing.add("wireshark")
        driver = connections.get("npcap") or environment.get("npcap", {})
        if driver.get("status") != "present":
            missing.add("npcap")
    return missing
