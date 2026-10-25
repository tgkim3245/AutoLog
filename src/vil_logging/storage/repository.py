"""Single-owner SQLite repository with atomic capture-number reservations.

Public operations run on the thread that created the repository. The app owns
the scheduling boundary; connections are never shared across UI/worker threads.
All indexes are decimal TEXT, including those in JSON snapshots.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from threading import get_ident
from typing import Any, Iterator
from uuid import uuid4

from vil_logging.contracts.models import (
    AppEvent,
    AppSettings,
    CapturePlan,
    Role,
    SessionPhase,
    utc_now,
)
from vil_logging.storage.naming import (
    CollisionError,
    build_plan,
    find_collisions,
    validate_settings,
)

logger = logging.getLogger(__name__)
_SCHEMA_VERSION = 2
_RESOLVED = (SessionPhase.COMPLETED.value, SessionPhase.FAILED.value)


class RepositoryError(RuntimeError):
    """Persistent metadata could not be safely changed."""


class StaleSettingsError(RepositoryError):
    """A preview or edit belongs to an older committed settings version."""


def _json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Unsupported persistent metadata value: {type(value).__name__}")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, default=_json_default)


def _settings_document(settings: AppSettings) -> dict[str, Any]:
    document = asdict(settings)
    # Keep the v2 settings document readable by older releases. New hardware
    # references live in an extension table that those releases can ignore.
    for role in ("can", "diag"):
        document.pop(role + "_hardware_baseline", None)
    document.pop("ethernet_compression", None)  # Older v2 releases ignore the extension table.
    document["next_index"] = str(settings.next_index)
    return document


class Repository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self._owner = get_ident()
        self._closed = False
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.db_path, timeout=5, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        try:
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=FULL")
            self._initialize()
            self._connection.execute("CREATE TABLE IF NOT EXISTS storage_preferences "
                                     "(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            self._connection.execute("CREATE TABLE IF NOT EXISTS hardware_references "
                                     "(role TEXT PRIMARY KEY, cfg TEXT NOT NULL, document TEXT NOT NULL)")
            self._connection.execute("CREATE TABLE IF NOT EXISTS settings_migrations "
                                     "(name TEXT PRIMARY KEY, applied_utc TEXT NOT NULL)")
        except BaseException:
            self._connection.close()
            raise
        logger.debug("storage.repository_opened", extra={
            "db_path": str(self.db_path), "schema_version": _SCHEMA_VERSION,
        })

    def _check_owner(self) -> None:
        if get_ident() != self._owner:
            raise RepositoryError("Repository must be used on its creator thread")
        if self._closed:
            raise RepositoryError("Repository has been closed")

    @contextmanager
    def _transaction(self, operation: str) -> Iterator[sqlite3.Connection]:
        self._check_owner()
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            yield self._connection
            self._connection.execute("COMMIT")
        except BaseException:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            logger.exception("storage.transaction_failed", extra={"operation": operation})
            raise

    def _initialize(self) -> None:
        version = self._connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in {0, 1, _SCHEMA_VERSION}:
            raise RepositoryError(f"Unsupported database schema {version}; expected {_SCHEMA_VERSION}")
        if version == _SCHEMA_VERSION:
            return
        if version == 1:
            backup_path = self.db_path.with_name(self.db_path.name + ".before-v2-" + uuid4().hex + ".bak")
            backup = sqlite3.connect(backup_path)
            try:
                self._connection.backup(backup)
                if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RepositoryError("Pre-migration backup verification failed")
            finally:
                backup.close()
            with self._transaction("migrate_v2") as connection:
                self._create_file_operations(connection)
                connection.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
            logger.info("storage.schema_migrated", extra={"backup_path": str(backup_path)})
            return
        with self._transaction("initialize") as connection:
            statements = (
                "CREATE TABLE settings (id INTEGER PRIMARY KEY CHECK(id=1), next_index TEXT NOT NULL, "
                "version INTEGER NOT NULL, document TEXT NOT NULL)",
                "CREATE TABLE sessions (session_id TEXT PRIMARY KEY, capture_index TEXT NOT NULL, "
                "prefix TEXT NOT NULL, phase TEXT NOT NULL, demo INTEGER NOT NULL, "
                "settings_version INTEGER NOT NULL, settings_document TEXT NOT NULL, "
                "plan_document TEXT NOT NULL, details TEXT NOT NULL, created_utc TEXT NOT NULL, "
                "updated_utc TEXT NOT NULL)",
                "CREATE TABLE capture_files (session_id TEXT NOT NULL REFERENCES sessions(session_id), "
                "role TEXT NOT NULL, filename TEXT NOT NULL, temp_path TEXT NOT NULL, "
                "final_path TEXT NOT NULL, state TEXT NOT NULL, PRIMARY KEY(session_id, role))",
                "CREATE TABLE events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, "
                "code TEXT NOT NULL, level TEXT NOT NULL, target TEXT NOT NULL, params TEXT NOT NULL, "
                "original TEXT NOT NULL, session_id TEXT)",
                "CREATE INDEX events_by_session ON events(session_id, event_id)",
            )
            for statement in statements:
                connection.execute(statement)
            self._create_file_operations(connection)
            connection.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")

    @staticmethod
    def _create_file_operations(connection):
        connection.execute("CREATE TABLE file_operations (operation_id TEXT PRIMARY KEY, "
                           "kind TEXT NOT NULL, status TEXT NOT NULL, document TEXT NOT NULL, "
                           "created_utc TEXT NOT NULL, updated_utc TEXT NOT NULL)")

    def _read_settings(self) -> AppSettings | None:
        row = self._connection.execute("SELECT * FROM settings WHERE id=1").fetchone()
        if row is None:
            return None
        document = json.loads(row["document"])
        for role in ("can", "diag"):
            reference = self._connection.execute("SELECT cfg,document FROM hardware_references WHERE role=?",
                                                 (role,)).fetchone()
            key = role + "_hardware_baseline"
            document[key] = reference["document"] if reference and reference["cfg"] == document.get(role + "_cfg", "") else ""
        compression = self._connection.execute("SELECT value FROM storage_preferences WHERE key=?",
                                                ("ethernet_compression",)).fetchone()
        document["ethernet_compression"] = compression["value"] if compression else "none"
        document["ethernet_buffer_mib"] = "64"  # Fixed application buffer; ignore legacy UI tuning.
        document.update(next_index=int(row["next_index"]), version=row["version"])
        return AppSettings(**document)

    @staticmethod
    def _write_settings(connection: sqlite3.Connection, settings: AppSettings) -> None:
        settings = replace(settings, ethernet_buffer_mib="64")
        connection.execute("INSERT INTO storage_preferences VALUES(?,?) ON CONFLICT(key) "
                           "DO UPDATE SET value=excluded.value",
                           ("ethernet_compression", settings.ethernet_compression))
        for role in ("can", "diag"):
            connection.execute("INSERT INTO hardware_references VALUES(?,?,?) ON CONFLICT(role) "
                               "DO UPDATE SET cfg=excluded.cfg,document=excluded.document",
                               (role, getattr(settings, role + "_cfg"), getattr(settings, role + "_hardware_baseline")))
        connection.execute(
            "INSERT INTO settings(id,next_index,version,document) VALUES(1,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET next_index=excluded.next_index, "
            "version=excluded.version, document=excluded.document",
            (str(settings.next_index), settings.version, _json(_settings_document(settings))),
        )

    def load_settings(self, default_output_dir: str = "") -> AppSettings:
        self._check_owner()
        settings = self._read_settings()
        if settings is not None:
            return settings
        with self._transaction("create_default_settings") as connection:
            # Another process may have initialized the row after our first read.
            settings = self._read_settings()
            if settings is None:
                settings = AppSettings(output_dir=default_output_dir)
                self._write_settings(connection, settings)
        return settings

    def restore_zipy_default_once(self) -> tuple[str, AppSettings]:
        """Repair pre-0.9.17 profiles once, preserving future intentional edits/deletion.

        The rule, settings version, event and migration marker commit together.
        Keep the v2 settings document unchanged for older-release compatibility.
        """
        from vil_logging.monitors.rules import (
            DEFAULT_RULE_NAME,
            DefaultRuleCapacityError,
            upgrade_zipy_defaults,
        )
        with self._transaction("restore_zipy_default_once") as connection:
            current = self._read_settings()
            if current is None:
                raise RepositoryError("Load settings before restoring the Zipy default")
            migration = "zipy-default-rule-v1"
            if connection.execute("SELECT 1 FROM settings_migrations WHERE name=?", (migration,)).fetchone():
                return "already_applied", current
            try:
                document = upgrade_zipy_defaults(current.monitor_rules_json)
            except DefaultRuleCapacityError:
                return "limit", current
            status = "present"
            if document != current.monitor_rules_json:
                current = replace(current, monitor_rules_json=document, version=current.version + 1)
                self._write_settings(connection, current)
                self._insert_event(connection, AppEvent("ZIPY_DEFAULT_RESTORED", params={"rule": DEFAULT_RULE_NAME}))
                status = "restored"
            connection.execute("INSERT INTO settings_migrations VALUES(?,?)", (migration, utc_now()))
            return status, current

    def save_settings(self, settings: AppSettings, roles: tuple[Role, ...]) -> AppSettings:
        self._check_owner()
        settings = replace(settings, ethernet_buffer_mib="64")
        validate_settings(settings, roles)
        preview = build_plan(settings, roles) if roles else None
        with self._transaction("save_settings") as connection:
            current = self._read_settings()
            if current is not None and settings.version != current.version:
                raise StaleSettingsError("Settings changed while this edit was open")
            if preview is not None and (collisions := find_collisions(preview)):
                raise CollisionError(collisions)
            if preview is not None:
                self.check_file_claims([str(file.final_path) for file in preview.files])
            updated = replace(settings, version=(current.version if current else settings.version) + 1)
            self._write_settings(connection, updated)
            self._insert_event(connection, AppEvent("settings.saved", params={
                "version": updated.version, "next_index": str(updated.next_index),
                "prefix": updated.prefix, "output_dir": updated.output_dir,
            }))
        logger.info("storage.settings_saved", extra={
            "settings_version": updated.version, "next_index": str(updated.next_index),
            "prefix": updated.prefix, "output_dir": updated.output_dir,
        })
        return updated

    def save_preferences(self, patch: dict[str, str]) -> AppSettings:
        """Remember user choices independently of recording/name preflight.

        An unplugged NIC or unavailable folder must remain visible on restart.
        Each patch merges into the latest committed settings, avoiding lost
        changes when file pickers and automatic discovery finish close together.
        Capture preparation still performs full filesystem/tool validation.
        """
        allowed = {"can_cfg", "diag_cfg", "tshark_path", "output_dir", "nic_id",
                   "language", "ethernet_format", "ethernet_compression", "ethernet_buffer_mib", "can_logging_block", "diag_logging_block", "monitor_rules_json",
                   "can_hardware_baseline", "diag_hardware_baseline"}
        if not isinstance(patch, dict) or set(patch) - allowed:
            raise RepositoryError("Unsupported connection preference fields")
        if any(not isinstance(value, str) or any(ord(char) < 32 for char in value)
               for value in patch.values()):
            raise RepositoryError("Connection preferences must be plain text")
        if "language" in patch and patch["language"] not in {"ko", "en", "zh"}:
            raise RepositoryError("Unsupported display language")
        if "ethernet_format" in patch and patch["ethernet_format"] not in {"pcap", "pcapng"}:
            raise RepositoryError("Unsupported Ethernet file format")
        if "ethernet_compression" in patch and patch["ethernet_compression"] not in {"none", "zip"}:
            raise RepositoryError("Unsupported Ethernet compression")
        if "ethernet_buffer_mib" in patch:
            from vil_logging.diagnostics.capture_quality import validate_buffer
            validate_buffer(patch["ethernet_buffer_mib"])
        if "monitor_rules_json" in patch:
            from vil_logging.monitors.rules import parse_rules
            parse_rules(patch["monitor_rules_json"])
        for key in ("can_logging_block", "diag_logging_block"):
            if key in patch and patch[key] and (not patch[key].isdecimal() or not 1 <= int(patch[key]) <= 128):
                raise RepositoryError("Logging Block must be a listed 1-based index")
        for key in ("can_hardware_baseline", "diag_hardware_baseline"):
            if key in patch:
                from vil_logging.diagnostics.canoe_hardware import parse_baseline
                parse_baseline(patch[key])
        with self._transaction("save_preferences") as connection:
            current = self._read_settings()
            if current is None:
                raise RepositoryError("Load settings before saving preferences")
            patch = dict(patch)
            if "ethernet_buffer_mib" in patch:
                patch["ethernet_buffer_mib"] = "64"
            for prefix in ("can", "diag"):
                cfg_key, block_key = prefix + "_cfg", prefix + "_logging_block"
                if cfg_key in patch and patch[cfg_key] != getattr(current, cfg_key) and block_key not in patch:
                    patch[block_key] = ""
                if cfg_key in patch and patch[cfg_key] != getattr(current, cfg_key):
                    patch[prefix + "_hardware_baseline"] = ""
            if all(getattr(current, key) == value for key, value in patch.items()):
                return current
            updated = replace(current, **patch, version=current.version + 1)
            self._write_settings(connection, updated)
            self._insert_event(connection, AppEvent("preferences.saved", params={
                "fields": sorted(patch), "version": updated.version,
            }))
        logger.info("storage.preferences_saved", extra={"fields": patch, "version": updated.version})
        return updated

    def reserve(self, plan: CapturePlan) -> AppSettings:
        """Durably save the immutable plan and consume its index in one commit.

        Call only after external preparation has been confirmed. This operation
        starts no external tool and creates no capture files, including in demo.
        """
        self._check_owner()
        if type(plan.index) is not int or type(plan.settings_version) is not int:
            raise RepositoryError("Capture index and settings version must be exact integers")
        with self._transaction("reserve") as connection:
            current = self._read_settings()
            if current is None:
                raise RepositoryError("Load or save settings before reserving a session")
            if (plan.settings_version != current.version or plan.index != current.next_index
                    or plan.prefix != current.prefix):
                raise StaleSettingsError("Capture plan no longer matches committed settings")
            validate_settings(current, plan.roles)
            expected = build_plan(current, plan.roles, demo=plan.demo, session_id=plan.session_id)
            if plan.files != expected.files:
                raise RepositoryError("Capture plan paths or names differ from committed settings")
            if collisions := find_collisions(plan):
                raise CollisionError(collisions)
            self.check_file_claims([str(file.final_path) for file in plan.files])
            document = asdict(plan)
            document["index"] = str(plan.index)
            connection.execute(
                "INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (plan.session_id, str(plan.index), plan.prefix, SessionPhase.PREPARING.value,
                 int(plan.demo), plan.settings_version, _json(_settings_document(current)),
                 _json(document), "{}", plan.created_utc, utc_now()),
            )
            connection.executemany(
                "INSERT INTO capture_files VALUES(?,?,?,?,?,?)",
                [(plan.session_id, file.role.value, file.filename, str(file.temp_path),
                  str(file.final_path), "planned") for file in plan.files],
            )
            updated = replace(current, next_index=plan.index + 1, version=current.version + 1)
            self._write_settings(connection, updated)
            self._insert_event(connection, AppEvent("session.reserved", session_id=plan.session_id, params={
                "index": str(plan.index), "next_index": str(updated.next_index),
                "demo": plan.demo, "roles": [role.value for role in plan.roles],
            }))
        logger.info("storage.session_reserved", extra={
            "session_id": plan.session_id, "index": str(plan.index),
            "next_index": str(updated.next_index), "demo": plan.demo,
            "files": [{"role": file.role.value, "temp_path": str(file.temp_path),
                       "final_path": str(file.final_path)} for file in plan.files],
        })
        return updated

    def update_session(self, session_id: str, phase: SessionPhase, **details: Any) -> None:
        self._check_owner()
        phase = SessionPhase(phase)
        with self._transaction("update_session") as connection:
            row = connection.execute("SELECT details FROM sessions WHERE session_id=?", (session_id,)).fetchone()
            if row is None:
                raise RepositoryError(f"Unknown session: {session_id}")
            merged = json.loads(row["details"])
            merged.update(details)
            connection.execute("UPDATE sessions SET phase=?,details=?,updated_utc=? WHERE session_id=?",
                               (phase.value, _json(merged), utc_now(), session_id))
        logger.debug("storage.session_updated", extra={
            "session_id": session_id, "phase": phase.value, "details": details,
        })

    def update_capture_file(self, session_id: str, role: Role, state: str, **details: Any) -> None:
        with self._transaction("update_capture_file") as connection:
            row = connection.execute("SELECT details FROM sessions WHERE session_id=?", (session_id,)).fetchone()
            if row is None:
                raise RepositoryError("Unknown capture session")
            changed = connection.execute("UPDATE capture_files SET state=? WHERE session_id=? AND role=?",
                                         (state, session_id, role.value))
            if changed.rowcount != 1:
                raise RepositoryError("Unknown capture file")
            merged = json.loads(row["details"])
            files = merged.setdefault("files", {})
            files.setdefault(role.value, {}).update(state=state, **details)
            connection.execute("UPDATE sessions SET details=?,updated_utc=? WHERE session_id=?",
                               (_json(merged), utc_now(), session_id))
        logger.info("storage.capture_file_updated", extra={"session_id": session_id, "role": role.value,
                                                          "state": state, "details": details})

    def captures(self, limit: int | None = 100, *, include_demo: bool = False) -> list[dict]:
        self._check_owner()
        condition = "" if include_demo else " WHERE demo=0"
        suffix = " ORDER BY rowid DESC" + (" LIMIT ?" if limit is not None else "")
        rows = self._connection.execute(
            "SELECT * FROM sessions" + condition + suffix,
            (limit,) if limit is not None else ()).fetchall()
        result = []
        for row in rows:
            session = dict(row)
            session["index"] = int(row["capture_index"])
            session["details"] = json.loads(row["details"])
            session["files"] = []
            for record in self._connection.execute("SELECT * FROM capture_files WHERE session_id=? "
                                                    "ORDER BY role", (row["session_id"],)):
                file = dict(record)
                file["metadata"] = session["details"].get("files", {}).get(file["role"], {})
                session["files"].append(file)
            result.append(session)
        return result

    def finish_manual_review(self, session_id: str, evidence: dict) -> None:
        """Keep files and consumed index; never certify an interrupted capture as success."""
        with self._transaction("finish_manual_review") as connection:
            row = connection.execute("SELECT phase,details FROM sessions WHERE session_id=?",
                                     (session_id,)).fetchone()
            if row is None or row["phase"] not in {"incomplete", "failed"}:
                raise RepositoryError("Session is not awaiting recovery")
            details = json.loads(row["details"])
            for file in connection.execute("SELECT role,state,temp_path FROM capture_files WHERE session_id=?",
                                           (session_id,)).fetchall():
                if file["state"] not in {"published", "deleted", "not_created", "unconfirmed"}:
                    connection.execute("UPDATE capture_files SET state='retained' WHERE session_id=? AND role=?",
                                       (session_id, file["role"]))
                    metadata = details.setdefault("files", {}).setdefault(file["role"], {})
                    metadata["state"] = "retained"
                    metadata.setdefault("actual_path", file["temp_path"])
            details["manual_review"] = {"timestamp": utc_now(), "recorders_stopped_by_user": True,
                                        "result": "failed_files_preserved", "evidence": evidence}
            connection.execute("UPDATE sessions SET phase='failed',details=?,updated_utc=? WHERE session_id=?",
                               (_json(details), utc_now(), session_id))
        logger.warning("storage.manual_review_finished", extra={"session_id": session_id})

    def file_operations(self, *, unresolved=False, limit=200) -> list[dict]:
        self._check_owner()
        condition = " WHERE status IN ('pending','review')" if unresolved else ""
        ordering = " ORDER BY rowid" if unresolved else " ORDER BY rowid DESC LIMIT ?"
        rows = self._connection.execute("SELECT * FROM file_operations" + condition + ordering,
                                        () if unresolved else (limit,)).fetchall()
        return [dict(row, document=json.loads(row["document"])) for row in rows]

    def check_file_claims(self, paths: list[str]) -> None:
        def key(path):
            return os.path.normcase(os.path.abspath(path))
        wanted = {key(path) for path in paths}
        for operation in self.file_operations(unresolved=True):
            for item in operation["document"]["items"]:
                if item["status"] in {"pending", "review"}:
                    claimed = {key(item[name]) for name in ("source", "destination") if item.get(name)}
                    if wanted & claimed:
                        raise RepositoryError("Unresolved file operation owns this path: " + item["source"])

    def begin_file_operation(self, operation_id: str, kind: str, document: dict) -> None:
        with self._transaction("file_operation_intent") as connection:
            connection.execute("INSERT INTO file_operations VALUES(?,?,?,?,?,?)",
                               (operation_id, kind, "pending", _json(document), utc_now(), utc_now()))
        logger.info("storage.file_operation_intent", extra={"operation_id": operation_id,
                                                           "kind": kind, "document": document})

    def record_file_operation(self, operation_id: str, document: dict, status: str,
                              updates: list[dict]) -> None:
        """Commit each filesystem result and its actual path together."""
        with self._transaction("file_operation_result") as connection:
            for item in updates:
                row = connection.execute("SELECT details FROM sessions WHERE session_id=?",
                                         (item["session_id"],)).fetchone()
                if row is None:
                    raise RepositoryError("Unknown file operation session")
                details = json.loads(row["details"])
                metadata = details.setdefault("files", {}).setdefault(item["role"], {})
                metadata.update(actual_path=item["actual_path"], state=item["state"],
                                file_identity=item["identity"], last_file_operation=operation_id)
                if item["state"] == "unconfirmed":
                    connection.execute("UPDATE capture_files SET state=? WHERE session_id=? AND role=?",
                                       (item["state"], item["session_id"], item["role"]))
                else:
                    connection.execute("UPDATE capture_files SET final_path=?,filename=?,state=? "
                                       "WHERE session_id=? AND role=?",
                                       (item["actual_path"], Path(item["actual_path"]).name, item["state"],
                                        item["session_id"], item["role"]))
                connection.execute("UPDATE sessions SET details=?,updated_utc=? WHERE session_id=?",
                                   (_json(details), utc_now(), item["session_id"]))
            connection.execute("UPDATE file_operations SET status=?,document=?,updated_utc=? "
                               "WHERE operation_id=?", (status, _json(document), utc_now(), operation_id))
        logger.info("storage.file_operation_result", extra={"operation_id": operation_id,
                                                           "status": status, "document": document})

    @staticmethod
    def _insert_event(connection: sqlite3.Connection, event: AppEvent) -> None:
        connection.execute(
            "INSERT INTO events(timestamp,code,level,target,params,original,session_id) VALUES(?,?,?,?,?,?,?)",
            (event.timestamp, event.code, event.level, event.target, _json(event.params),
             event.original, event.session_id),
        )

    def append_event(self, event: AppEvent) -> None:
        with self._transaction("append_event") as connection:
            self._insert_event(connection, event)
        logger.debug("storage.event_appended", extra={
            "event_code": event.code, "event_level": event.level,
            "target": event.target, "session_id": event.session_id,
        })

    def recent_events(self, limit: int = 500) -> list[AppEvent]:
        self._check_owner()
        if type(limit) is not int or limit < 0:
            raise ValueError("Event limit must be a nonnegative integer")
        rows = self._connection.execute("SELECT * FROM events ORDER BY event_id DESC LIMIT ?", (limit,)).fetchall()
        return [AppEvent(code=row["code"], level=row["level"], target=row["target"],
                         params=json.loads(row["params"]), original=row["original"],
                         timestamp=row["timestamp"], session_id=row["session_id"])
                for row in reversed(rows)]

    def recover_incomplete(self) -> list[dict[str, Any]]:
        """Mark abandoned reservations incomplete; leave all capture files alone."""
        recovered = []
        with self._transaction("recover_incomplete") as connection:
            rows = connection.execute(
                "SELECT * FROM sessions WHERE phase NOT IN (?,?) ORDER BY created_utc", _RESOLVED,
            ).fetchall()
            for row in rows:
                plan = json.loads(row["plan_document"])
                details = json.loads(row["details"])
                newly_recovered = row["phase"] != SessionPhase.INCOMPLETE.value
                if newly_recovered:
                    details.update(recovered_previous_phase=row["phase"], recovered_utc=utc_now())
                    connection.execute("UPDATE sessions SET phase=?,details=?,updated_utc=? WHERE session_id=?",
                                       (SessionPhase.INCOMPLETE.value, _json(details), utc_now(), row["session_id"]))
                result = {"session_id": row["session_id"], "index": int(row["capture_index"]),
                          "prefix": row["prefix"], "phase": SessionPhase.INCOMPLETE.value,
                          "previous_phase": details.get("recovered_previous_phase", row["phase"]),
                          "demo": bool(row["demo"]),
                          "files": plan["files"], "roles": plan["roles"], "details": details}
                recovered.append(result)
                if newly_recovered:
                    self._insert_event(connection, AppEvent(
                        "session.recovered_incomplete", level="WARNING", session_id=row["session_id"],
                        params={"index": row["capture_index"], "previous_phase": row["phase"]},
                    ))
        for result in recovered:
            logger.warning("storage.session_recovered_incomplete", extra=result)
        return recovered

    def close(self) -> None:
        if self._closed:
            return
        self._check_owner()
        self._connection.close()
        self._closed = True
        logger.debug("storage.repository_closed", extra={"db_path": str(self.db_path)})
