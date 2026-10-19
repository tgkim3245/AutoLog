"""Bounded metadata parsing, actual format headers and no-replace publication."""

import io
import queue
import struct
from types import SimpleNamespace

import pytest

from vil_logging.adapters.tshark import TSharkCapture, capture_header_ready, parse_summary
from vil_logging.contracts.models import CaptureFilePlan, Role
from vil_logging.storage.capture_files import cleanup_work_directory, publish_capture


@pytest.mark.parametrize("ipv4,ipv6,mac,expected", [
    ("192.0.2.1", "", "02:00:00:00:00:01", "192.0.2.1"),
    ("", "2001:db8::1", "02:00:00:00:00:01", "2001:db8::1"),
    ("", "", "02:00:00:00:00:01", "02:00:00:00:00:01"),
    ("", "", "", ""),
])
def test_packet_metadata_uses_available_address_without_inventing_fields(ipv4, ipv6, mac, expected):
    packet = parse_summary("\t".join(("1700000000.123456", mac, "ff:ff:ff:ff:ff:ff", ipv4, ipv6,
                                      "", "", "ARP", "42")), "session")
    assert packet.source == expected and packet.destination == "ff:ff:ff:ff:ff:ff"
    assert packet.length == 42 and packet.session_id == "session"
    assert packet.timestamp == "2023-11-14T22:13:20.123+00:00"


@pytest.mark.parametrize("line", ["one\tfield", "\t".join(["bad-time"] + [""] * 7 + ["42"]),
                                "\t".join(["1"] + [""] * 7 + ["-1"])])
def test_invalid_metadata_is_rejected(line):
    with pytest.raises(ValueError):
        parse_summary(line, "session")


def test_zero_packet_header_is_ready_but_wrong_or_truncated_header_is_not(tmp_path):
    file = tmp_path / "empty.pcap"
    header = struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
    file.write_bytes(header)
    assert capture_header_ready(file, "pcap")
    assert not capture_header_ready(file, "pcapng")
    file.write_bytes(header[:12])
    assert not capture_header_ready(file, "pcap")


def test_pcapng_readiness_requires_interface_block_not_section_magic_alone(tmp_path):
    file = tmp_path / "empty.pcapng"
    section = struct.pack("<IIIHHqI", 0x0A0D0D0A, 28, 0x1A2B3C4D, 1, 0, -1, 28)
    file.write_bytes(section)
    assert not capture_header_ready(file, "pcapng")
    file.write_bytes(section + struct.pack("<IIHHII", 1, 20, 1, 0, 65535, 20))
    assert capture_header_ready(file, "pcapng")


@pytest.mark.parametrize("fault", ["none", "collision", "changed"])
def test_publication_preserves_existing_or_changed_files(tmp_path, fault):
    working = tmp_path / "working.pcap"
    final = tmp_path / "final.pcap"
    working.write_bytes(b"verified capture")
    value = working.stat()
    inspection = {"bytes": value.st_size, "mtime_ns": value.st_mtime_ns, "inode": value.st_ino}
    plan = CaptureFilePlan(Role.ETHERNET, "final.pcap", working, final)
    if fault == "collision":
        final.write_bytes(b"precious original")
        with pytest.raises(FileExistsError):
            publish_capture(plan, inspection)
        assert final.read_bytes() == b"precious original"
        assert working.read_bytes() == b"verified capture"
    elif fault == "changed":
        working.write_bytes(b"changed after inspection")
        with pytest.raises(ValueError):
            publish_capture(plan, inspection)
        assert not final.exists() and working.exists()
    else:
        assert publish_capture(plan, inspection) == final
        assert final.read_bytes() == b"verified capture" and not working.exists()


def test_work_directory_cleanup_removes_only_empty_work_directories(tmp_path):
    work_root = tmp_path / ".vil_work"
    session_dir = work_root / "session-1"
    session_dir.mkdir(parents=True)
    assert cleanup_work_directory(session_dir)
    assert not work_root.exists()

    session_dir.mkdir(parents=True)
    unfinished = session_dir / "unfinished.pcap"
    unfinished.write_bytes(b"keep for recovery")
    assert not cleanup_work_directory(session_dir)
    assert unfinished.read_bytes() == b"keep for recovery"

    unfinished.unlink()
    other_session = work_root / "session-2"
    other_session.mkdir()
    assert cleanup_work_directory(session_dir)
    assert not session_dir.exists() and other_session.is_dir() and work_root.is_dir()


def test_full_ui_queue_and_bad_metadata_do_not_stop_stdout_consumption():
    row = b"1700000000\t\t\t127.0.0.1\t\t127.0.0.1\t\tUDP\t50\n"
    capture = TSharkCapture(queue.Queue(maxsize=1))
    capture.session_id = "owned-session"
    capture.process = SimpleNamespace(stdout=io.BytesIO(row + b"invalid\n" + row * 2))
    capture._observer = SimpleNamespace(process=capture.process)
    capture._consume_stdout()
    assert capture._parsed == 3 and capture._dropped == 2 and capture._parse_errors == 1
    assert capture.packets.qsize() == 1
