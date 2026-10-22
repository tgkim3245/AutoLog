import json
import os
import subprocess
import sys

from vil_logging.app import developer_log_directory


def test_packaged_developer_logs_live_beside_the_executable(tmp_path):
    executable = tmp_path / "AutoLog" / "AutoLog.exe"
    assert developer_log_directory(tmp_path / "profile", executable=executable,
                                   frozen=True) == executable.parent / "developer_logs"


def test_explicit_data_dir_keeps_smoke_logs_isolated(tmp_path):
    assert developer_log_directory(tmp_path / "profile", use_data_dir=True,
                                   frozen=False) == tmp_path / "profile" / "developer_logs"


def test_full_application_starts_simulates_and_exits_cleanly(tmp_path):
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run(
        [sys.executable, "-m", "vil_logging", "--smoke-test", "--data-dir", str(tmp_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
        env=environment,
    )
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["smoke_passed"] is True
    assert report["canoe_popup_verified"] is True
    assert report["developer_log_default"] is True
    log_file = tmp_path / "developer_logs" / "One_Click_Log_developer.jsonl"
    assert log_file.exists()
    events = {json.loads(line)["event"] for line in log_file.read_text(encoding="utf-8").splitlines()}
    assert "app.startup" in events
    assert "SESSION_COMPLETED" in events
    assert "capture.failure_popup_shown" in events and "smoke.canoe_popup_verified" in events


def test_always_on_diagnostics_flush_and_capture_application_events(tmp_path):
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run(
        [sys.executable, "-m", "vil_logging", "--smoke-test", "--smoke-debug-log",
         "--data-dir", str(tmp_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
        env=environment,
    )
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["developer_log_default"] is True
    assert report["developer_log_path"]
    files = list((tmp_path / "developer_logs").glob("One_Click_Log_developer.jsonl*"))
    assert len(files) == 1
    records = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]
    events = {record["event"] for record in records}
    assert "app.startup" in events
    assert "smoke.debug_log_verified" in events
    assert "command.result" in events
    assert "SESSION_COMPLETED" in events
    assert "developer_log.disabled" in events
