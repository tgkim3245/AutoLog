from __future__ import annotations

import hashlib
import json
import logging
import queue
import struct
import subprocess
import threading
import time
import zipfile
from pathlib import Path

import pytest

from vil_logging.diagnostics import DebugLogError, DebugLogService


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_disabled_default_does_not_create_files_and_is_not_persisted(tmp_path: Path) -> None:
    directory = tmp_path / "app_data"
    service = DebugLogService(directory)
    assert not service.enabled
    assert service.log_path is None
    service.log("ignored", useful="metadata")
    service.exception("ignored_error", RuntimeError("ignored"))
    service.disable()
    service.close()
    assert not directory.exists()

    first = DebugLogService(directory)
    first_path = first.enable()
    first.close()
    next_launch = DebugLogService(directory)
    assert not next_launch.enabled
    assert next_launch.log_path is None
    assert next_launch.enable() == first_path
    next_launch.close()
    assert first_path.exists()


def test_enable_collects_header_without_starting_subprocess(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def reject_subprocess(*args, **kwargs):
        raise AssertionError("Developer log metadata must not launch an external process")

    monkeypatch.setattr(subprocess, "Popen", reject_subprocess)
    service = DebugLogService(tmp_path)
    path = service.enable()
    service.close()
    header = _records(path)[0]
    assert header["fields"]["process_bits"] == struct.calcsize("P") * 8
    assert header["fields"]["platform"]


def test_enabled_json_metadata_unicode_exception_and_package_logging(tmp_path: Path) -> None:
    service = DebugLogService(tmp_path)
    original_level = logging.getLogger("vil_logging").level
    path = service.enable()
    assert path.exists()
    assert service.enable() == path
    service.log("세션.시작", session_number="1234567890123456789012345", target="CAN", count=2)
    logging.getLogger("vil_logging.adapter").debug("adapter ready: %s", "준비", extra={"target": "Diag"})
    logging.getLogger("vil_logging.control").info(
        "controller.transition", extra={"fields": {"state": "ready", "target": "CAN"}, "operation": "start"},
    )
    try:
        raise ValueError("장비 연결 실패")
    except ValueError as error:
        service.exception("adapter.failed", error, operation="connect")
    try:
        raise OSError("native logging failure")
    except OSError:
        logging.getLogger("vil_logging.capture").exception("capture.failed")
    service.disable()
    assert logging.getLogger("vil_logging").level == original_level
    assert service.log_path == path
    records = _records(path)
    assert records[0]["event"] == "developer_log.enabled"
    assert records[0]["fields"]["app_version"]
    assert records[0]["fields"]["python_version"]
    assert records[0]["fields"]["platform"]
    assert records[-1]["event"] == "developer_log.disabled"
    assert all(record["timestamp_utc"].endswith("+00:00") for record in records)
    assert all(record["pid"] > 0 and record["tid"] > 0 for record in records)
    assert all(record["monotonic_ns"] > 0 for record in records)
    session = next(record for record in records if record["event"] == "세션.시작")
    assert session["fields"]["session_number"] == "1234567890123456789012345"
    adapter = next(record for record in records if record["event"] == "adapter ready: 준비")
    assert adapter["level"] == "DEBUG"
    assert adapter["fields"]["target"] == "Diag"
    transition = next(record for record in records if record["event"] == "controller.transition")
    assert transition["fields"] == {"state": "ready", "target": "CAN", "operation": "start"}
    failure = next(record for record in records if record["event"] == "adapter.failed")
    assert failure["exception"]["type"] == "ValueError"
    assert "장비 연결 실패" in failure["exception"]["traceback"]
    assert "test_enabled_json_metadata" in failure["exception"]["traceback"]
    native = next(record for record in records if record["event"] == "capture.failed")
    assert native["exception"]["type"] == "OSError"
    service.close()


def test_disable_stops_saving_and_reenable_uses_the_same_rolling_file(tmp_path: Path) -> None:
    service = DebugLogService(tmp_path)
    first = service.enable()
    service.log("first.event")
    service.disable()
    before = first.read_bytes()
    service.log("after.disable")
    logging.getLogger("vil_logging.adapter").error("after.disable.native")
    service.exception("after.disable.error", ValueError("ignored"))
    service.disable()
    assert first.read_bytes() == before
    second = service.enable()
    assert second == first
    service.log("second.event")
    service.close()
    service.close()
    assert not service.enabled
    assert first.read_bytes() != before
    assert any(record["event"] == "second.event" for record in _records(second))
    with pytest.raises(RuntimeError, match="closed"):
        service.enable()


def test_rotation_is_bounded_and_final_records_are_flushed(tmp_path: Path) -> None:
    service = DebugLogService(tmp_path, max_bytes=1200, backup_count=2)
    path = service.enable()
    for index in range(60):
        service.log("rotating.event", index=index, detail="연결 상태 " * 10)
    service.close()
    files = list(path.parent.glob(path.name + "*"))
    assert len(files) == 3
    all_records = [record for file in files for record in _records(file)]
    assert any(record["fields"].get("index") == 59 for record in all_records)
    assert _records(path)[-1]["event"] == "developer_log.disabled"
    assert not any(record["fields"].get("index") == 0 for record in all_records)


def test_rotation_bound_is_preserved_across_application_restarts(tmp_path: Path) -> None:
    path = None
    for launch in range(2):
        service = DebugLogService(tmp_path, max_bytes=1200, backup_count=2)
        current = service.enable()
        assert path is None or current == path
        path = current
        for index in range(40):
            service.log("restart.rotation", launch=launch, index=index, detail="connection status " * 10)
        service.close()

    assert path is not None
    files = list(path.parent.glob(path.name + "*"))
    assert len(files) == 3
    assert sum(file.stat().st_size for file in files) <= 3 * 1200


def test_capture_content_is_redacted_but_metadata_survives(tmp_path: Path) -> None:
    service = DebugLogService(tmp_path)
    path = service.enable()
    service.log("capture.metadata", packet_count=4, payload=b"private", vehicle_data="private",
                detail={"packet_bytes": [1, 2, 3], "status": "ready"}, opaque=b"private")
    service.close()
    record = next(record for record in _records(path) if record["event"] == "capture.metadata")
    assert record["fields"]["packet_count"] == 4
    assert record["fields"]["detail"]["status"] == "ready"
    assert "private" not in json.dumps(record)
    assert "redacted" in record["fields"]["vehicle_data"]
    assert "redacted" in record["fields"]["opaque"]


def test_async_write_failure_is_reported_and_resources_are_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = DebugLogService(tmp_path)
    service.enable()
    output = service._file_handler
    assert output is not None

    def fail_write(record: logging.LogRecord) -> None:
        raise OSError("simulated full disk")

    monkeypatch.setattr(output, "emit", fail_write)
    service.log("write.must.fail")
    logging.getLogger("vil_logging.control").info("control.must.continue")
    with pytest.raises(DebugLogError, match="storage failed"):
        service.disable()
    assert not service.enabled
    assert output.stream is None
    assert isinstance(service.last_error, OSError)
    assert service.failed_record_count > 0
    with pytest.raises(DebugLogError):
        service.check_health()
    with pytest.raises(DebugLogError):
        service.close()


def test_open_failure_does_not_claim_enabled(tmp_path: Path) -> None:
    (tmp_path / "developer_logs").write_text("not a directory", encoding="utf-8")
    service = DebugLogService(tmp_path)
    with pytest.raises(OSError):
        service.enable()
    assert not service.enabled
    assert service.log_path is None
    service.close()


def test_queue_failure_preserves_control_flow_and_health_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = DebugLogService(tmp_path)
    service.enable()
    handler = service._handler
    assert handler is not None
    original_enqueue = handler.enqueue

    def fail_enqueue(record: logging.LogRecord) -> None:
        raise queue.Full("simulated backpressure")

    monkeypatch.setattr(handler, "enqueue", fail_enqueue)
    service.log("cannot.enqueue")
    service.exception("cannot.enqueue.exception", ValueError("capture still runs"))
    logging.getLogger("vil_logging.control").info("control.must.continue")
    assert service.failed_record_count == 3
    assert service.queue_overflow_count == 3
    assert service.last_failed_event == "control.must.continue"
    with pytest.raises(DebugLogError, match="queue overflowed"):
        service.check_health()
    # A recovered queue can retain a final, reviewable loss summary in the file.
    monkeypatch.setattr(handler, "enqueue", original_enqueue)
    with pytest.raises(DebugLogError):
        service.close()
    assert not service.enabled
    assert service.log_path is not None
    final = _records(service.log_path)[-1]
    assert final["event"] == "developer_log.disabled"
    assert final["fields"]["queue_overflow_count"] == 3
    assert final["fields"]["last_failed_event"] == "control.must.continue"


def test_bug_report_export_contains_current_and_rotated_logs(tmp_path: Path) -> None:
    service = DebugLogService(tmp_path, max_bytes=1200, backup_count=2)
    path = service.enable()
    for index in range(50):
        service.log("report.event", index=index, detail="connection status " * 12)

    report = service.export_report(tmp_path / "Desktop")
    assert report.parent.name == "Desktop"
    assert report.name.startswith("One_Click_Log_BugReport_")
    with zipfile.ZipFile(report) as archive:
        names = archive.namelist()
        assert path.name in names
        assert f"{path.name}.1" in names
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["send_to"] == "Taegon.Kim"
        assert "To_Taegon.Kim" in report.name
        assert archive.testzip() is None
        for item in manifest["files"]:
            content = archive.read(item["name"])
            assert len(content) == item["bytes"]
            assert hashlib.sha256(content).hexdigest() == item["sha256"]
            assert content == (path.parent / item["name"]).read_bytes()
        all_records = [json.loads(line) for name in names
                       if name != "manifest.json"
                       for line in archive.read(name).decode("utf-8").splitlines()]
    service.close()
    assert any(record["event"] == "report.event" for record in all_records)


def test_export_is_a_complete_snapshot_while_background_logging_continues(tmp_path):
    service = DebugLogService(tmp_path, max_bytes=2500, backup_count=2)
    service.enable()
    began = threading.Event()
    stop = threading.Event()

    def write():
        index = 0
        while not stop.is_set():
            logging.getLogger("vil_logging.test").debug("background.event", extra={"index": index})
            began.set()
            index += 1
            time.sleep(0.002)

    writer = threading.Thread(target=write)
    writer.start()
    try:
        assert began.wait(2)
        report = service.export_report(tmp_path / "Desktop")
        assert writer.is_alive()
        with zipfile.ZipFile(report) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            assert archive.testzip() is None
            for item in manifest["files"]:
                content = archive.read(item["name"])
                assert len(content) == item["bytes"]
                assert hashlib.sha256(content).hexdigest() == item["sha256"]
                assert all(json.loads(line)["timestamp_utc"] for line in content.splitlines())
        again = service.export_report(tmp_path / "Desktop")
        assert again != report and again.is_file() and report.is_file()
    finally:
        stop.set()
        writer.join(timeout=3)
        service.close()
