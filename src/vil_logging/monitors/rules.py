"""Versioned receive rules, including the user-requested Zipy default."""

import ipaddress
import json
import re
from dataclasses import asdict, dataclass

MAX_RULES = 16


def address(value, *, mac=False):
    if not isinstance(value, str):
        raise ValueError("Addresses must be text")
    if not value:
        return ""
    if mac:
        value = value.replace("-", ":").lower()
        if not re.fullmatch(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}", value):
            raise ValueError("MAC 형식을 확인하세요. / Invalid MAC address")
        return value
    return str(ipaddress.ip_address(value))


@dataclass(frozen=True)
class EthernetRule:
    id: str
    name: str
    timeout_ms: int
    grace_ms: int
    max_delay_ms: int
    recovery_count: int
    protocol: str = ""
    destination_ip: str = ""
    destination_mac: str = ""
    expected_ip: str = ""
    expected_mac: str = ""
    source_mac_prefix: str = ""
    minimum_pps: int = 0

    def __post_init__(self):
        for key in ("id", "name"):
            value = getattr(self, key)
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= 80 or any(ord(c) < 32 for c in value):
                raise ValueError("규칙 이름을 입력하세요. / A rule name and ID are required")
        for key, low, high in (("timeout_ms", 1, 86400000), ("grace_ms", 0, 86400000),
                               ("max_delay_ms", 1, self.timeout_ms), ("recovery_count", 1, 1000000)):
            value = getattr(self, key)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{key}: {low}~{high} 범위의 정수 필요 / integer required")
        if not isinstance(self.protocol, str) or (self.protocol and
                not re.fullmatch(r"[A-Za-z0-9_./:+-]{1,64}", self.protocol)):
            raise ValueError("프로토콜 표기를 확인하세요. / Invalid protocol name")
        object.__setattr__(self, "protocol", self.protocol.upper())
        for key in ("destination_ip", "destination_mac", "expected_ip", "expected_mac"):
            object.__setattr__(self, key, address(getattr(self, key), mac=key.endswith("mac")))
        if (self.expected_ip or self.expected_mac) and not (self.destination_ip or self.destination_mac):
            raise ValueError("출처 비교에는 대상 목적지 IP 또는 MAC이 필요합니다. / "
                             "Source checks require an independent destination IP or MAC selector.")
        if not isinstance(self.source_mac_prefix, str):
            raise ValueError("Source MAC prefix must be text")
        prefix = self.source_mac_prefix.replace("-", ":").lower().rstrip(":")
        if prefix and not re.fullmatch(r"[0-9a-f]{2}(?::[0-9a-f]{2}){0,5}", prefix):
            raise ValueError("Invalid source MAC prefix (example: 02:00:00)")
        object.__setattr__(self, "source_mac_prefix", prefix)
        if type(self.minimum_pps) is not int or not 0 <= self.minimum_pps <= 10000000:
            raise ValueError("minimum_pps: 0~10000000 integer required")

    def in_flow(self, packet):
        return ((not self.protocol or packet.protocol.upper() == self.protocol) and
                (not self.source_mac_prefix or (packet.source_mac.lower() + ":").startswith(self.source_mac_prefix + ":")) and
                (not self.destination_ip or packet.destination_ip == self.destination_ip) and
                (not self.destination_mac or packet.destination_mac.lower() == self.destination_mac))

    def expected_source(self, packet):
        return ((not self.expected_ip or packet.source_ip == self.expected_ip) and
                (not self.expected_mac or packet.source_mac.lower() == self.expected_mac))


def parse_rules(document: str) -> tuple[EthernetRule, ...]:
    if not isinstance(document, str) or len(document) > 65536:
        raise ValueError("Monitor settings must be bounded JSON text")
    if not document:
        return ()
    value = json.loads(document)
    if (not isinstance(value, dict) or set(value) != {"version", "ethernet"}
            or type(value["version"]) is not int or value["version"] != 1
            or not isinstance(value["ethernet"], list) or len(value["ethernet"]) > MAX_RULES):
        raise ValueError("지원하지 않는 감시 설정 형식 / Unsupported monitor settings")
    try:
        rules = tuple(EthernetRule(**item) for item in value["ethernet"])
    except TypeError as error:
        raise ValueError("감시 기준을 모두 입력하세요. / Complete all monitor criteria.") from error
    if len({rule.id for rule in rules}) != len(rules):
        raise ValueError("Duplicate monitor rule IDs")
    return rules


def encode_rules(rules) -> str:
    document = json.dumps({"version": 1, "ethernet": [asdict(rule) for rule in rules]},
                          ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    parse_rules(document)
    return document


def default_rules_json():
    # A presence/rate selector, not an exclusive source allow-list or capture filter.
    return encode_rules([EthernetRule("zipy-source-020000", "Zipy · 02:00:00", 3000, 5000, 1500, 10,
                                     source_mac_prefix="02:00:00", minimum_pps=100)])
