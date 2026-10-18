"""Safe, one-time migration of user settings from the previous product name."""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)


def migrate_legacy_profile(source_dir: Path, destination_dir: Path) -> bool:
    """Copy a legacy SQLite profile into a new app-data folder once.

    SQLite's backup API includes committed WAL data. The original database and
    capture files are left in place. Existing destination state is never
    overwritten. Only the old default filename prefix is renamed.
    """
    source = Path(source_dir) / "state.sqlite3"
    destination_dir = Path(destination_dir)
    destination = destination_dir / "state.sqlite3"
    if destination.exists() or not source.is_file():
        return False

    destination_dir.mkdir(parents=True, exist_ok=True)
    temporary = destination_dir / f".state.sqlite3.{uuid4().hex}.tmp"
    try:
        with closing(sqlite3.connect(source, timeout=5)) as old_db, \
                closing(sqlite3.connect(temporary)) as new_db:
            old_db.backup(new_db)
            integrity = new_db.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise sqlite3.DatabaseError(f"Legacy profile integrity check failed: {integrity}")
            row = new_db.execute("SELECT document FROM settings WHERE id=1").fetchone()
            if row:
                document = json.loads(row[0])
                if document.get("prefix") in {"VIL", "Auto_Log"}:
                    document["prefix"] = "AutoLog"
                    new_db.execute("UPDATE settings SET document=? WHERE id=1", (
                        json.dumps(document, ensure_ascii=False, allow_nan=False),
                    ))
            new_db.commit()
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        logger.exception("storage.legacy_profile_migration_failed", extra={
            "source": str(source), "destination": str(destination),
        })
        raise

    logger.info("storage.legacy_profile_migrated", extra={
        "source": str(source), "destination": str(destination),
    })
    return True
