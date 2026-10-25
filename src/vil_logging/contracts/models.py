"""Application states are independent of external tool implementation details."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from vil_logging.monitors.rules import default_rules_json


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class Role(StrEnum):
    CAN = "can"
    DIAG = "diag"
    ETHERNET = "ethernet"

    @property
    def label(self) -> str:
        return {self.CAN: "CAN", self.DIAG: "Diag", self.ETHERNET: "Zipy"}[self]


class ConnectionState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    READY = "ready"
    ERROR = "error"
    UNKNOWN = "unknown"


class RecordingState(StrEnum):
    IDLE = "idle"
    STARTING = "starting"
    RECORDING = "recording"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"
    UNKNOWN = "unknown"


class ObservationState(StrEnum):
    NOT_MONITORED = "not_monitored"
    NOT_CONFIGURED = "not_configured"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"
    NORMAL = "normal"
    WARNING = "warning"


class SessionPhase(StrEnum):
    IDLE = "idle"
    PREPARING = "preparing"
    STARTING = "starting"
    RECORDING = "recording"
    PARTIAL = "partial"
    STOPPING = "stopping"
    COMPLETED = "completed"
    FAILED = "failed"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True)
class AppSettings:
    prefix: str = "One_Click_Log"
    next_index: int = 1
    output_dir: str = ""
    ethernet_format: str = "pcap"
    ethernet_compression: str = "none"
    ethernet_buffer_mib: str = "64"
    can_cfg: str = ""
    diag_cfg: str = ""
    can_logging_block: str = ""
    diag_logging_block: str = ""
    can_hardware_baseline: str = ""
    diag_hardware_baseline: str = ""
    nic_id: str = ""
    tshark_path: str = ""
    language: str = "ko"
    monitor_rules_json: str = field(default_factory=default_rules_json)
    version: int = 1


@dataclass(frozen=True)
class CaptureFilePlan:
    role: Role
    filename: str
    temp_path: Path
    final_path: Path


@dataclass(frozen=True)
class CapturePlan:
    session_id: str
    index: int
    prefix: str
    roles: tuple[Role, ...]
    files: tuple[CaptureFilePlan, ...]
    settings_version: int
    demo: bool = False
    created_utc: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class TargetSnapshot:
    role: Role
    connection: ConnectionState = ConnectionState.DISCONNECTED
    recording: RecordingState = RecordingState.IDLE
    observation: ObservationState = ObservationState.NOT_MONITORED
    generation: int = 0
    evidence: str = ""
    observation_details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AppEvent:
    code: str
    level: str = "INFO"
    target: str = "app"
    params: dict[str, Any] = field(default_factory=dict)
    original: str = ""
    timestamp: str = field(default_factory=utc_now)
    session_id: str | None = None


@dataclass(frozen=True)
class PacketSummary:
    timestamp: str
    source: str
    destination: str
    protocol: str
    length: int
    source_mac: str = ""
    destination_mac: str = ""
    session_id: str = ""
    source_ip: str = ""
    destination_ip: str = ""
    captured_epoch: float | None = None
