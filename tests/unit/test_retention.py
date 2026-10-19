import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from vil_logging.contracts.models import AppEvent
from vil_logging.storage.repository import Repository
from vil_logging.storage.retention import maintain


@pytest.fixture
def repository(tmp_path):
    repo = Repository(tmp_path / "state.sqlite3")
    repo.load_settings()
    db = repo._connection
    for i in range(106):
        db.execute("INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
            str(i), str(i), "AutoLog", "completed" if i else "incomplete", 0, 1, "{}", "{}", "{}",
            "2020-01-01T00:00:00.000+00:00", "2020-01-01T00:00:00.000+00:00"))
        file = tmp_path / f"AutoLog_{i}.pcap"
        file.write_bytes(b"preserved")
        db.execute("INSERT INTO capture_files VALUES(?,?,?,?,?,?)", (str(i), "ethernet", file.name, str(file), str(file), "published"))
        db.execute("INSERT INTO file_operations VALUES(?,?,?,?,?,?)", (str(i), "rename", "completed", "{}",
            "2020-01-01T00:00:00.000+00:00", "2020-01-01T00:00:00.000+00:00"))
    repo.begin_file_operation("unresolved", "rename", {"items": [{"session_id": "1", "status": "pending"}]})
    for i in range(600):
        repo.append_event(AppEvent("fixture", session_id="0" if i == 0 else "1" if i == 1 else None,
                                   timestamp="2020-01-01T00:00:00.000+00:00"))
    yield repo
    repo.close()


def test_archives_before_pruning_and_keeps_files_and_unresolved_metadata(repository):
    before = repository.load_settings()
    result = maintain(repository, now=datetime(2026, 10, 19, tzinfo=UTC))
    assert result["status"] == "archived"
    assert result["counts"]["sessions"] == 4
    with gzip.open(result["path"], "rt", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream]
    assert len(rows) == sum(result["counts"].values())
    assert {row["row"]["session_id"] for row in rows if row["table"] == "sessions"} == {"2", "3", "4", "5"}
    db = repository._connection
    assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 502
    assert db.execute("SELECT COUNT(*) FROM sessions WHERE session_id IN ('0','1')").fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM file_operations WHERE operation_id='unresolved'").fetchone()[0] == 1
    assert all(path.read_bytes() == b"preserved" for path in repository.db_path.parent.glob("*.pcap"))
    assert repository.load_settings() == before
    assert maintain(repository)["status"] == "unchanged"


def test_archive_write_failure_keeps_all_metadata(repository, monkeypatch):
    original = Path.open
    def fail_archive(path, mode="r", *args, **kwargs):
        if mode == "xb":
            raise OSError("disk full")
        return original(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", fail_archive)
    with pytest.raises(OSError, match="disk full"):
        maintain(repository)
    assert repository._connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 106
    assert repository._connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 600


def test_archive_reverification_failure_does_not_prune(repository, monkeypatch):
    monkeypatch.setattr(gzip, "open", lambda *_a, **_k: (_ for _ in ()).throw(OSError("bad archive")))
    with pytest.raises(OSError, match="bad archive"):
        maintain(repository)
    assert repository._connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 106


def test_count_limits_apply_to_recent_history(tmp_path):
    repo = Repository(tmp_path / "state.db")
    try:
        repo.load_settings()
        for _ in range(550):
            repo.append_event(AppEvent("recent"))
        result = maintain(repo, event_limit=500)
        assert result["counts"]["events"] == 50
        assert len(repo.recent_events(1000)) == 500
    finally:
        repo.close()
