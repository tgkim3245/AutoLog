"""Pure capture plans plus Windows filename and output preflight checks.

Ethernet ZIP plans retain a raw working name and publish a .pcap[ng].zip archive.
No capture file or work directory is created by this module.
"""

from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

from vil_logging.contracts.models import AppSettings, CaptureFilePlan, CapturePlan, Role

logger = logging.getLogger(__name__)
_FORBIDDEN = frozenset('<>:"/\\|?*')
_RESERVED = re.compile(r"^(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)", re.I)


class NamingError(ValueError):
    """A name, index, or output location is unsuitable for a capture."""


class CollisionError(NamingError):
    def __init__(self, paths: list[Path]) -> None:
        self.paths = paths
        super().__init__("Output name already exists: " + ", ".join(map(str, paths)))


def parse_index(text: str) -> int:
    """Parse an ASCII decimal index without floating point or size truncation."""
    if not isinstance(text, str) or not re.fullmatch(r"[0-9]+", text):
        raise NamingError("Next index must be a nonnegative decimal integer")
    # Real filenames are at most 255 UTF-16 units; reject impossible input before
    # Python's defensive very-large-decimal conversion limit is reached.
    normalized = text.lstrip("0") or "0"
    if len(normalized) > 255:
        raise NamingError("The index is too long for a Windows filename")
    return int(normalized)


def _units(value: str) -> int:
    try:
        return len(value.encode("utf-16-le")) // 2
    except UnicodeEncodeError as error:
        raise NamingError("Names must contain valid Unicode characters") from error


def validate_prefix(prefix: str) -> None:
    if not isinstance(prefix, str):
        raise NamingError("Prefix must be text")
    if any(character in _FORBIDDEN or ord(character) < 32 for character in prefix):
        raise NamingError("Prefix contains a Windows filename separator or forbidden character")
    if prefix.endswith((".", " ")):
        raise NamingError("Prefix must not end with a dot or space")
    if _units(prefix) > 255:
        raise NamingError("Prefix is too long for a Windows filename")


def capture_prefix(prefix: str) -> str:
    """Separate a user-entered prefix from the numeric index with one underscore."""
    validate_prefix(prefix)
    return prefix if prefix.endswith("_") else prefix + "_"


def renamed_filename(name: str, role: Role, extension: str) -> str:
    """Build a previous-capture name from the literal base name, with no index."""
    if not isinstance(name, str) or not name.strip():
        raise NamingError("Enter a filename")
    validate_prefix(name)
    if not isinstance(role, Role):
        raise NamingError("Capture role is invalid")
    allowed = {"pcap", "pcapng", "pcap.zip", "pcapng.zip"} if role == Role.ETHERNET else {"blf"}
    if extension not in allowed:
        raise NamingError("Unsupported capture extension")
    marker = "_Diag" if role == Role.DIAG else ""
    filename = f"{name}{marker}.{extension}"
    if _RESERVED.match(filename):
        raise NamingError(f"Windows reserves this filename: {filename}")
    if _units(filename) > 255:
        raise NamingError(f"Capture filename exceeds 255 UTF-16 units: {filename}")
    return filename


def capture_extension(settings: AppSettings, role: Role) -> str:
    if role != Role.ETHERNET:
        return "blf"
    return settings.ethernet_format + (".zip" if settings.ethernet_compression == "zip" else "")


def _filename(settings: AppSettings, role: Role) -> str:
    marker = "Diag_" if role == Role.DIAG else ""
    extension = capture_extension(settings, role)
    filename = f"{capture_prefix(settings.prefix)}{marker}{settings.next_index}.{extension}"
    if _RESERVED.match(filename):
        raise NamingError(f"Windows reserves this filename: {filename}")
    if _units(filename) > 255:
        raise NamingError(f"Capture filename exceeds 255 UTF-16 units: {filename}")
    return filename


def _output_dir(settings: AppSettings) -> Path:
    if not isinstance(settings.output_dir, str) or not settings.output_dir.strip():
        raise NamingError("Select an output directory")
    if any(ord(character) < 32 for character in settings.output_dir):
        raise NamingError("Output directory contains a control character")
    return Path(settings.output_dir).expanduser().resolve()


def validate_settings(
    settings: AppSettings, roles: tuple[Role, ...], *, check_output: bool = True
) -> None:
    """Validate settings; output preflight probes a unique, disposable file.

    An empty selection is valid while editing settings. ``build_plan`` requires
    at least one target. A successful probe cannot guarantee future disk writes.
    """
    validate_prefix(settings.prefix)
    from vil_logging.monitors.rules import parse_rules
    parse_rules(settings.monitor_rules_json)
    from vil_logging.diagnostics.capture_quality import validate_buffer
    validate_buffer(settings.ethernet_buffer_mib)
    if type(settings.next_index) is not int or settings.next_index < 0:
        raise NamingError("Next index must be a nonnegative integer")
    if settings.next_index.bit_length() > 850:
        raise NamingError("The index is too long for a Windows filename")
    if settings.ethernet_format not in {"pcap", "pcapng"}:
        raise NamingError("Ethernet format must be pcap or pcapng")
    if settings.ethernet_compression not in {"none", "zip"}:
        raise NamingError("Ethernet compression must be none or zip")
    if settings.language not in {"ko", "en", "zh"}:
        raise NamingError("Language must be ko, en or zh")
    if type(settings.version) is not int or settings.version < 1:
        raise NamingError("Settings version must be a positive integer")
    for choice in (settings.can_logging_block, settings.diag_logging_block):
        if not isinstance(choice, str) or (choice and (not choice.isdecimal() or not 1 <= int(choice) <= 128)):
            raise NamingError("Choose a listed CANoe Logging Block")
    if any(not isinstance(role, Role) for role in roles) or len(set(roles)) != len(roles):
        raise NamingError("Capture targets must be unique Role values")
    output = _output_dir(settings)
    # Even with no current selection the next index must fit a supported name.
    for role in roles or tuple(Role):
        filename = _filename(settings, role)
        work_path = output / ".vil_work" / ("0" * 36) / filename
        if _units(str(work_path)) >= 260:
            raise NamingError(f"Capture path exceeds the supported Windows path length: {work_path}")
    if check_output:
        if not output.is_dir():
            raise NamingError(f"Output directory does not exist or is not accessible: {output}")
        try:
            with tempfile.TemporaryFile(prefix=".vil_write_probe_", dir=output) as probe:
                probe.write(b"VIL output preflight\n")
                probe.flush()
        except OSError as error:
            logger.exception("storage.output_preflight_failed", extra={"output_dir": str(output)})
            raise NamingError(f"Output directory is not writable: {output}: {error}") from error
    logger.debug("storage.settings_validated", extra={
        "roles": [role.value for role in roles], "output_dir": str(output),
        "prefix": settings.prefix, "index": str(settings.next_index),
        "settings_version": settings.version, "check_output": check_output,
    })


def build_plan(
    settings: AppSettings,
    roles: tuple[Role, ...],
    *,
    demo: bool = False,
    session_id: str | None = None,
) -> CapturePlan:
    validate_settings(settings, roles, check_output=False)
    if not roles:
        raise NamingError("Select at least one capture target")
    if type(demo) is not bool:
        raise NamingError("Demo mode must be a boolean")
    identifier = str(uuid4()) if session_id is None else session_id
    try:
        if str(UUID(identifier)) != identifier:
            raise ValueError("Session ID must be a canonical UUID")
    except (ValueError, AttributeError, TypeError) as error:
        raise NamingError("Session ID must be a canonical UUID") from error
    output = _output_dir(settings)
    files = tuple(
        CaptureFilePlan(
            role=role, filename=(filename := _filename(settings, role)),
            temp_path=output / ".vil_work" / identifier / (filename[:-4] if role == Role.ETHERNET
                                                       and settings.ethernet_compression == "zip" else filename),
            final_path=output / filename,
        )
        for role in roles
    )
    return CapturePlan(
        session_id=identifier, index=settings.next_index, prefix=settings.prefix,
        roles=roles, files=files, settings_version=settings.version, demo=demo,
    )


def find_collisions(plan: CapturePlan) -> list[Path]:
    """Return occupied final paths, including directories and dangling symlinks."""
    paths = [file.final_path for file in plan.files
             if file.final_path.exists() or file.final_path.is_symlink()]
    if paths:
        logger.warning("storage.output_collision", extra={
            "session_id": plan.session_id, "paths": [str(path) for path in paths],
        })
    return paths
