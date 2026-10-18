"""Internal application commands, not names of external CANoe APIs."""

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from vil_logging.contracts.models import Role, utc_now


@dataclass(frozen=True)
class Command:
    action: str
    role: Role
    session_id: str
    generation: int = 1
    command_id: str = field(default_factory=lambda: uuid4().hex)
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CommandResult:
    command: Command
    success: bool
    state: str
    evidence: str = ""
    pid: int = 0
    timestamp: str = field(default_factory=utc_now)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkerProgress:
    command: Command
    fields: dict[str, Any]
    pid: int = 0


@dataclass(frozen=True)
class FakeBehavior:
    start_delay: float = 0.05
    stop_delay: float = 0.03
    fail_start: bool = False
    fail_stop: bool = False
    fail_after: float | None = None
    crash_on_start: bool = False
