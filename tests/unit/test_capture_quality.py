import io
import queue
import struct
import time
from types import SimpleNamespace

import pytest
from PySide6.QtTest import QSignalSpy

from vil_logging.adapters.tshark import TSharkCapture
from vil_logging.contracts.models import AppSettings
from vil_logging.diagnostics.capture_quality import CaptureMetrics, validate_buffer
from vil_logging.diagnostics.load_test import MAGIC, inspect_sequences, validate_load
from vil_logging.storage.pcapng_stats import capture_loss_report
from vil_logging.storage.repository import Repository
from vil_logging.ui.quality_dialog import QualityDialog
from vil_logging.ui.settings_dialog import SettingsDialog


def block(kind, body, order="<"):
    length = len(body) + 12
    return struct.pack(order + "II", kind, length) + body + struct.pack(order + "I", length)


def section(order="<"):
    return block(0x0A0D0D0A, struct.pack(order + "IHHq", 0x1A2B3C4D, 1, 0, -1), order)


def interface(order="<"):
    return block(1, struct.pack(order + "HHI", 1, 0, 65535), order)


def statistics(*, driver=None, os=None, stamp=1, identifier=0, order="<"):
    body = struct.pack(order + "III", identifier, 0, stamp)
    for code, value in ((5, driver), (7, os)):
        if value is not None:
            body += struct.pack(order + "HHQ", code, 8, value)
    return block(5, body + struct.pack(order + "HH", 0, 0), order)


@pytest.mark.parametrize("order", ["<", ">"])
def test_optional_counters_latest_snapshot_not_sum_and_endian_safe(tmp_path, order):
    path = tmp_path / "test.pcapng"
    path.write_bytes(section(order) + interface(order) + statistics(driver=2, os=1, order=order) +
                     statistics(driver=5, os=3, stamp=2, order=order))
    result = capture_loss_report(path, "pcapng")
    assert result["status"] == "loss_reported"
    assert result["driver_dropped"] == 5 and result["os_dropped"] == 3
    assert result["interfaces"][0]["stats_entries"] == 2


def test_zero_is_reported_only_when_present_and_missing_interface_is_unknown(tmp_path):
    path = tmp_path / "test.pcapng"
    path.write_bytes(section() + interface() + statistics(driver=0))
    result = capture_loss_report(path, "pcapng")
    assert result["status"] == "reported" and result["driver_dropped"] == 0
    assert result["os_dropped"] is None
    path.write_bytes(path.read_bytes() + interface())
    result = capture_loss_report(path, "pcapng")
    assert result["status"] == "unknown" and result["driver_dropped"] is None
    assert capture_loss_report(path, "pcap")["driver_dropped"] is None


def test_sections_have_independent_interface_ids_and_missing_later_counters_do_not_erase_known_loss(tmp_path):
    path = tmp_path / "test.pcapng"
    path.write_bytes(section() + interface() + statistics(driver=2) + statistics(stamp=2) +
                     section(">") + interface(">") + statistics(driver=0, os=0, order=">"))
    result = capture_loss_report(path, "pcapng")
    assert result["status"] == "loss_reported" and result["driver_dropped"] is None
    assert len(result["interfaces"]) == 2


@pytest.mark.parametrize("fault", ["truncated", "counter_decrease", "time_decrease", "unknown_interface", "length"])
def test_corrupt_or_ambiguous_statistics_are_unknown_never_zero(tmp_path, fault):
    path = tmp_path / "test.pcapng"
    data = section() + interface() + statistics(driver=3, stamp=2)
    data += {"truncated": b"\x00", "counter_decrease": statistics(driver=2, stamp=3),
             "time_decrease": statistics(driver=4, stamp=1), "unknown_interface": statistics(identifier=5),
             "length": struct.pack("<III", 2, 0xFFFFFFFC, 0)}[fault]
    path.write_bytes(data)
    result = capture_loss_report(path, "pcapng")
    assert result["status"] == "unknown" and result["driver_dropped"] is None and result["error"]


def test_metadata_inspection_skips_large_frame_block_and_obeys_timeout(tmp_path):
    path = tmp_path / "large.pcapng"
    with path.open("wb") as target:
        target.write(section() + interface())
        size = 16 * 1024 * 1024
        target.write(struct.pack("<II", 0xBAD, size))
        target.seek(size - 12, 1)
        target.write(struct.pack("<I", size))
        target.write(statistics(driver=0, os=0))
    assert capture_loss_report(path, "pcapng")["driver_dropped"] == 0
    assert capture_loss_report(path, "pcapng", timeout=-1)["status"] == "unknown"


@pytest.mark.parametrize("value", ["0", "1025", "1.5", "-1", "６４", "", 64, None])
def test_capture_buffer_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        validate_buffer(value)


def test_legacy_buffer_settings_are_normalized_to_fixed_64(tmp_path):
    repo = Repository(tmp_path / "state.sqlite3")
    assert repo.load_settings().ethernet_buffer_mib == "64"
    saved = repo.save_preferences({"ethernet_buffer_mib": "128"})
    with pytest.raises(ValueError):
        repo.save_preferences({"ethernet_buffer_mib": "0"})
    assert repo.load_settings() == saved
    repo.close()
    repo = Repository(tmp_path / "state.sqlite3")
    try:
        assert repo.load_settings().ethernet_buffer_mib == "64"
    finally:
        repo.close()


def test_metrics_delta_rates_freeze_and_stat_errors_are_telemetry_only(tmp_path, monkeypatch):
    now = [1.0]
    metrics = CaptureMetrics(monotonic=lambda: now[0])
    path = tmp_path / "sample.pcap"
    path.write_bytes(b"a" * 1000)
    monkeypatch.setattr("vil_logging.diagnostics.capture_quality.shutil.disk_usage", lambda path: SimpleNamespace(free=512))
    now[0] = 2
    first = metrics.sample(path, 100, last_delay=4, max_delay=10)
    assert first["parsed_pps"] == 100 and first["file_growth_bps"] == 1000 and first["low_space"]
    path.write_bytes(b"b" * 3000)
    now[0] = 4
    second = metrics.sample(path, 500)
    assert second["parsed_pps"] == 200 and second["file_growth_bps"] == 1000
    metrics.finish()
    now[0] = 50
    assert metrics.sample(path, 500)["elapsed_seconds"] == 3
    path.unlink()
    assert metrics.sample(path, 500)["file_bytes"] == 3000  # Final evidence survives archival/move.
    assert metrics.sample(tmp_path / "absent", 500)["error"]


def test_receive_loop_delay_and_display_drops_are_independent_of_file_stats():
    now = time.time()
    row = f"{now - .05}\t\t\t127.0.0.1\t\t127.0.0.1\t\tUDP\t50\n".encode()
    capture = TSharkCapture(queue.Queue(maxsize=1))
    capture.process = SimpleNamespace(stdout=io.BytesIO(row * 3))
    capture._consume_stdout()
    assert capture._parsed == 3 and capture._dropped == 2
    assert capture._last_delay >= 50 and capture._max_delay >= capture._last_delay


def pcap(path, token, numbers, *, corrupt=False):
    header = struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 0)
    with path.open("wb") as target:
        target.write(header)
        for number in numbers:
            payload = MAGIC + token + struct.pack("!Q", number) + b"\xa5" * 32
            if corrupt:
                payload = payload[:-1] + b"x"
            packet = b"simulated-link-header" + payload
            target.write(struct.pack("<IIII", 1, 0, len(packet), len(packet)) + packet)


def test_numbered_scanner_checks_identity_content_duplicates_and_missing(tmp_path):
    path, token = tmp_path / "fixture.pcap", b"0" * 16
    pcap(path, token, [0, 1, 2])
    assert inspect_sequences(path, token, 3, 64)["passed"]
    pcap(path, token, [0, 0, 2, 4])
    result = inspect_sequences(path, token, 3, 64)
    assert result["missing"] == 1 and result["duplicates"] == 1 and result["out_of_range"] == 1
    assert result["missing_examples"] == [1]
    pcap(path, token, [0], corrupt=True)
    assert inspect_sequences(path, token, 1, 64)["invalid_payloads"] == 1
    pcap(path, b"1" * 16, [0])
    assert inspect_sequences(path, token, 1, 64)["foreign_packets"] == 1
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(ValueError, match="Truncated"):
        inspect_sequences(path, token, 1, 64)


@pytest.mark.parametrize("values", [(0, 1000, 512), (7201, 10, 512), (10, 100001, 512), (10, 1, 63), (1000, 100000, 512)])
def test_load_parameters_bound_fixture_size(values):
    with pytest.raises(ValueError):
        validate_load(*values)


def test_quality_ui_unknown_stale_and_final_samples_are_distinct(qtbot):
    dialog = QualityDialog()
    qtbot.addWidget(dialog)
    assert "아직" in dialog.status.text()
    data = {"state": "recording", "sampled_epoch": time.time(), "parsed_packets": 25,
            "display_drops": 20, "metrics": {"file_bytes": 4096},
            "capture_loss": {"driver_dropped": None, "os_dropped": None}}
    dialog.set_report(data)
    assert dialog.values["display"].text() == "20" and "확인 불가" in dialog.values["loss"].text()
    dialog.set_report({**data, "sampled_epoch": time.time() - 10})
    assert "갱신 지연" in dialog.status.text()
    dialog.set_report({**data, "state": "archived", "packet_count": 25, "sampled_epoch": 1})
    assert "보관 완료" in dialog.status.text() and "25 / 25" == dialog.values["counts"].text()
    dialog.set_language("en")
    assert "Unknown" in dialog.values["loss"].text() and "lossless" in dialog.note.text()


def test_buffer_is_fixed_and_legacy_ui_choice_is_not_exposed(qtbot):
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.set_settings(AppSettings(output_dir="C:/captures", ethernet_buffer_mib="256", version=4))
    assert not hasattr(dialog, "buffer_input")
    spy = QSignalSpy(dialog.settings_applied)
    dialog._apply()
    assert spy.at(0)[0].ethernet_buffer_mib == "64"
