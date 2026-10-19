"""Archive old resolved metadata before pruning it; never touch capture files."""

import gzip
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4


def maintain(repository, *, now=None, days=90, event_limit=10000, session_limit=1000):
    repository._check_owner()
    if days < 1 or event_limit < 500 or session_limit < 100:
        raise ValueError("Retention must preserve 500 events and 100 recent sessions")
    db = repository._connection
    cutoff = ((now or datetime.now(UTC)) - timedelta(days=days)).isoformat(timespec="milliseconds")
    archive = None
    counts = {}
    with repository._transaction("history_retention"):
        protected = set()
        for row in db.execute("SELECT document FROM file_operations WHERE status != 'completed'"):
            protected.update(item.get("session_id") for item in json.loads(row[0]).get("items", []))
        db.execute("CREATE TEMP TABLE IF NOT EXISTS prune_sessions(id TEXT PRIMARY KEY)")
        db.execute("CREATE TEMP TABLE IF NOT EXISTS prune_events(id INTEGER PRIMARY KEY)")
        db.execute("CREATE TEMP TABLE IF NOT EXISTS prune_operations(id TEXT PRIMARY KEY)")
        db.execute("DELETE FROM prune_sessions")
        db.execute("DELETE FROM prune_events")
        db.execute("DELETE FROM prune_operations")
        operations = db.execute("SELECT operation_id,updated_utc FROM file_operations WHERE status='completed' ORDER BY rowid DESC")
        for index, row in enumerate(operations):
            if index >= 100 and (index >= session_limit or row["updated_utc"] < cutoff):
                db.execute("INSERT INTO prune_operations VALUES(?)", (row["operation_id"],))
        completed = db.execute("SELECT session_id,updated_utc FROM sessions WHERE phase='completed' ORDER BY rowid DESC")
        for index, row in enumerate(completed):
            if index >= 100 and (index >= session_limit or row["updated_utc"] < cutoff) and row["session_id"] not in protected:
                db.execute("INSERT INTO prune_sessions VALUES(?)", (row["session_id"],))
        # Failed/incomplete/active sessions remain fully available for recovery/review.
        db.execute("INSERT INTO prune_events SELECT event_id FROM events WHERE "
                   "event_id NOT IN (SELECT event_id FROM events ORDER BY event_id DESC LIMIT 500) AND "
                   "(timestamp < ? OR event_id NOT IN (SELECT event_id FROM events ORDER BY event_id DESC LIMIT ?)) AND "
                   "(session_id IS NULL OR session_id NOT IN (SELECT session_id FROM sessions WHERE phase != 'completed'))",
                   (cutoff, event_limit))
        for session in protected:
            db.execute("DELETE FROM prune_events WHERE id IN (SELECT event_id FROM events WHERE session_id=?)", (session,))
        queries = {
            "sessions": "SELECT * FROM sessions WHERE session_id IN (SELECT id FROM prune_sessions)",
            "capture_files": "SELECT * FROM capture_files WHERE session_id IN (SELECT id FROM prune_sessions)",
            "events": "SELECT * FROM events WHERE event_id IN (SELECT id FROM prune_events)",
            "file_operations": "SELECT * FROM file_operations WHERE operation_id IN (SELECT id FROM prune_operations)",
        }
        counts = {table: db.execute("SELECT COUNT(*) FROM (" + query + ")").fetchone()[0]
                  for table, query in queries.items()}
        if not any(counts.values()):
            return {"status": "unchanged", "counts": counts}
        folder = repository.db_path.parent / "history_archive"
        folder.mkdir(exist_ok=True)
        archive = folder / ("AutoLog_history_" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ_") + uuid4().hex + ".jsonl.gz")
        digest = hashlib.sha256()
        # Any export failure rolls back the DB. Completed exports survive a later crash.
        with archive.open("xb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
                for table, query in queries.items():
                    for row in db.execute(query):
                        line = (json.dumps({"table": table, "row": dict(row)}, ensure_ascii=False) + "\n").encode("utf-8")
                        digest.update(line)
                        compressed.write(line)
            raw.flush()
            os.fsync(raw.fileno())
        verified = hashlib.sha256()
        with gzip.open(archive, "rb") as stream:
            while chunk := stream.read(1024 * 1024):
                verified.update(chunk)
        if verified.digest() != digest.digest():
            raise OSError("History archive verification failed; original metadata retained")
        db.execute("DELETE FROM capture_files WHERE session_id IN (SELECT id FROM prune_sessions)")
        db.execute("DELETE FROM sessions WHERE session_id IN (SELECT id FROM prune_sessions)")
        db.execute("DELETE FROM events WHERE event_id IN (SELECT id FROM prune_events)")
        db.execute("DELETE FROM file_operations WHERE operation_id IN (SELECT id FROM prune_operations)")
    # SQLite reuses free pages. Avoid an unbounded VACUUM at startup.
    return {"status": "archived", "counts": counts, "path": str(archive), "sha256": digest.hexdigest()}
