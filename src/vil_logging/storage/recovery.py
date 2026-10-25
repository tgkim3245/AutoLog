"""Explicit recovery of journalled captures; never reconnect to external recorders."""

import csv
import hashlib
import io
import json
import logging
import subprocess
import tempfile
import zipfile
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

from vil_logging.adapters.external import external_environment
from vil_logging.contracts.models import CaptureFilePlan, Role, utc_now
from vil_logging.diagnostics.environment import _tool_candidates
from vil_logging.storage.blf import inspect_blf
from vil_logging.storage.blf_snapshot import (
    cleanup_finalization_files,
    cleanup_retained_source,
    finalization_paths,
    snapshot_path,
)
from vil_logging.storage.capture_files import (
    capture_source,
    cleanup_work_directory,
    cleanup_zip_source,
    prepare_capture_zip,
)
from vil_logging.storage.file_access import ExclusiveFile, matches, observe
from vil_logging.storage.file_service import FileManagementError, FileService

log = logging.getLogger(__name__)
SETTLED = {"published", "deleted", "not_created", "retained", "unconfirmed"}


def _token(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def _evidence(path):
    try:
        return {"path": str(path), "present": True, "identity": observe(Path(path))}
    except FileNotFoundError:
        return {"path": str(path), "present": False}
    except (OSError, ValueError) as error:
        return {"path": str(path), "error": str(error)}


def _paths(file):
    paths = [file["temp_path"], file["final_path"], file["metadata"].get("actual_path", file["temp_path"])]
    if file["role"] in {"can", "diag"}:
        paths.append(str(snapshot_path(Path(file["temp_path"]))))
        capture = CaptureFilePlan(Role(file["role"]), file["filename"], Path(file["temp_path"]), Path(file["final_path"]))
        evidence = file["metadata"].get("inspection") or file["metadata"].get("stop_evidence", {})
        paths.extend(str(path) for path, _ in finalization_paths(capture, evidence))
    if file["role"] == "ethernet" and Path(file["final_path"]).name == Path(file["temp_path"]).name + ".zip":
        paths.append(file["temp_path"] + ".zip")
    return list(dict.fromkeys(paths))


def inspect_recovery_file(path: Path, extension: str, tshark_path: str) -> dict:
    """Read the whole file; structural validity does not establish lossless acquisition."""
    before = observe(path)
    # An existing writer blocks even the inspection attempt.
    with ExclusiveFile(path, before):
        pass
    if extension == "zip":
        # Verify CRC by full read and inspect the contained capture using the same tool.
        with zipfile.ZipFile(path) as zipped, tempfile.TemporaryDirectory(prefix="OneClickLog-verify-") as folder:
            members = zipped.infolist()
            if len(members) != 1 or members[0].is_dir() or Path(members[0].filename).name != members[0].filename:
                raise ValueError("Capture ZIP must contain one plain capture filename")
            member = members[0]
            target = Path(folder) / member.filename
            if target.suffix not in {".pcap", ".pcapng"}:
                raise ValueError("Unsupported capture ZIP member")
            with zipped.open(member) as reader, target.open("xb") as writer:
                while chunk := reader.read(1024 * 1024):
                    writer.write(chunk)
            result = inspect_recovery_file(target, target.suffix[1:], tshark_path)
            result = {key: value for key, value in result.items() if key not in {"inode", "device", "bytes", "mtime_ns"}}
    elif extension == "blf":
        result = inspect_blf(path)
    elif extension in {"pcap", "pcapng"}:
        sibling = Path(tshark_path).parent if tshark_path else None
        capinfos = next((tool for tool in _tool_candidates("capinfos", sibling_dir=sibling)
                         if tool.is_file()), None)
        if capinfos is None:
            raise FileManagementError("Wireshark의 capinfos.exe가 필요합니다. 설정에서 TShark 경로를 확인하세요. / "
                                      "capinfos.exe is required; check the TShark location in Settings.")
        checked = subprocess.run([str(capinfos), "-T", "-B", "-Q", "-r", "-t", "-c", str(path)],
                                 stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=60,
                                 env=external_environment(),
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if checked.returncode:
            raise ValueError("캡처 전체 읽기 실패 / Capture read failed: " + checked.stderr[-4096:])
        rows = list(csv.reader(io.StringIO(checked.stdout), delimiter="\t"))
        if len(rows) != 1 or len(rows[0]) != 3:
            raise ValueError("Unrecognized capinfos result")
        actual, count = rows[0][1], int(rows[0][2])
        if actual not in ({"pcap", "nsecpcap"} if extension == "pcap" else {"pcapng"}) or count < 0:
            raise ValueError("Capture format does not match its extension")
        result = {"actual_format": actual, "packet_count": count,
                  "validation": "capinfos_full_read", "warning": checked.stderr[-4096:]}
    else:
        raise ValueError("Unsupported recovery file extension")
    if not matches(observe(path), before):
        raise ValueError("검사 중 파일이 바뀌었습니다. / File changed during inspection.")
    return {**result, **before, "recorders_stopped_by_user": True,
            "recovery_validation": "structural_read_only", "recovery_utc": utc_now()}


class RecoveryService:
    def __init__(self, repository):
        self.repo = repository
        self.files = FileService(repository)

    def report(self):
        sessions = []
        for session in self.repo.captures(limit=None, include_demo=True):
            if session["phase"] != "incomplete" and not (
                    session["phase"] == "failed" and any(file["state"] not in SETTLED
                                                         for file in session["files"])):
                continue
            view = {key: session[key] for key in ("session_id", "index", "prefix", "phase", "demo", "created_utc")}
            view["files"] = [{**file, "candidates": [_evidence(path) for path in _paths(file)]}
                             for file in session["files"]]
            view["token"] = _token(view)
            sessions.append(view)
        operations = []
        for operation in self.repo.file_operations(unresolved=True):
            view = {**operation, "evidence": [
                _evidence(item[key]) for item in operation["document"]["items"]
                for key in ("source", "destination") if item.get(key)]}
            view["token"] = _token(view)
            operations.append(view)
        return {"sessions": sessions, "operations": operations}

    @staticmethod
    def _selected(rows, key, identifier, token, stopped):
        if stopped is not True:
            raise FileManagementError("먼저 외부 기록 종료를 확인하세요. / Confirm all external recording has stopped.")
        row = next((row for row in rows if row[key] == identifier), None)
        if row is None or row["token"] != token:
            raise FileManagementError("파일·기록 상태가 바뀌었습니다. CANoe의 수동 기록이 정지됐는지 확인한 뒤 "
                                      "새로 고치고 다시 선택하세요. / Recovery selection changed; stop any manual "
                                      "CANoe logging, refresh and select again.")
        return row

    def publish(self, session_id, role, token, stopped, tshark_path=""):
        session = self._selected(self.report()["sessions"], "session_id", session_id, token, stopped)
        if session["demo"]:
            raise FileManagementError("Simulation does not create capture files")
        file = next((file for file in session["files"] if file["role"] == role), None)
        if not file or file["state"] in SETTLED:
            raise FileManagementError("This capture is not awaiting publication")
        self.repo.check_file_claims(_paths(file))
        inspection = {"finalization_files": file["metadata"].get("stop_evidence", {}).get("finalization_files", []),
                      **file["metadata"].get("inspection", {})}
        capture_file = CaptureFilePlan(Role(role), file["filename"], Path(file["temp_path"]), Path(file["final_path"]))
        source, destination = capture_source(capture_file, inspection), capture_file.final_path
        if file["state"] == "publishing" and destination.exists():
            expected = {key: inspection[key] for key in ("inode", "bytes", "mtime_ns") if key in inspection}
            if not matches(observe(destination), expected):
                raise FileManagementError("Published capture identity changed; existing files are preserved.")
            source = destination
        elif not source.exists():
            # Normal publication may have moved the file just before its DB update failed.
            expected = inspection
            expected = {key: expected[key] for key in ("inode", "bytes", "mtime_ns") if key in expected}
            if file["state"] != "publishing" or not matches(observe(destination), expected):
                raise FileManagementError("작업 파일을 확인할 수 없습니다. 기존 파일은 유지합니다. / "
                                          "Working file identity is unconfirmed; existing output is preserved.")
            source = destination
        elif destination.exists() or destination.is_symlink():
            raise FileExistsError(f"기존 파일을 보존합니다. / Existing output: {destination}")
        log.info("recovery.inspection_started", extra={"session_id": session_id, "role": role, "path": str(source)})
        inspection = {**inspection, **inspect_recovery_file(source, "blf" if role in {"can", "diag"} else source.suffix[1:], tshark_path)}
        if source != destination:
            prepare_capture_zip(capture_file, inspection, before_publish=lambda prepared:
                self.repo.update_capture_file(session_id, Role(role), "publishing",
                    actual_path=prepared["zip_archive"]["path"], inspection=prepared))
            source = capture_source(capture_file, inspection)
        item = {"session_id": session_id, "role": role, "source": str(source),
                "destination": str(destination), "identity": {key: inspection[key]
                    for key in ("device", "inode", "bytes", "mtime_ns")}, "status": "pending"}
        identifier = uuid4().hex
        document = {"items": [item], "inspection": inspection, "manual": True}
        with ExclusiveFile(source, item["identity"]) as handle:
            self.repo.begin_file_operation(identifier, "recover_publish", document)
            try:
                if source != destination:
                    handle.move(destination)
                item.update(status="renamed" if source != destination else "unchanged", actual_path=str(destination))
            except (OSError, ValueError) as error:
                item.update(status="not_applied", error=str(error))
                self.files._commit(identifier, document, "blocked", [])
                raise
            self.files._commit(identifier, document, "completed", [self.files._update(item, str(destination))])
        # Persisted identity is sufficient for interrupted journal reconciliation.
        # Keep validation separately for display/audit; failure here cannot lose the move journal.
        self.repo.update_capture_file(session_id, Role(role), "published", inspection=inspection)
        try:
            cleanup_zip_source(capture_file, inspection)
        except (OSError, ValueError):
            log.info("recovery.zip_source_cleanup_deferred", extra={"session_id": session_id})
        if inspection.get("retained_source"):
            try:
                cleanup_retained_source(capture_file, inspection)
            except (OSError, ValueError):
                log.info("recovery.blf_source_cleanup_deferred", extra={"session_id": session_id})
        if inspection.get("finalization_files"):
            try:
                inspection["finalization_files"] = cleanup_finalization_files(capture_file, inspection)
                self.repo.update_capture_file(session_id, Role(role), "published", inspection=inspection)
            except (OSError, ValueError):
                log.info("recovery.blf_finalization_cleanup_deferred", extra={"session_id": session_id})
        cleanup_work_directory(Path(file["temp_path"]).parent)
        log.info("recovery.file_published", extra={"session_id": session_id, "role": role,
                                                   "inspection": inspection, "operation_id": identifier})
        return {"path": str(destination), "inspection": inspection}

    @staticmethod
    def _hold_candidates(stack, candidates):
        seen = set()
        for candidate in candidates:
            path = candidate["path"]
            if path in seen:
                continue
            seen.add(path)
            if candidate.get("error"):
                raise FileManagementError(candidate["error"])
            if candidate.get("present"):
                stack.enter_context(ExclusiveFile(Path(path), candidate["identity"]))
            elif _evidence(path) != candidate:
                raise FileManagementError("File appeared during recovery; refresh first")

    def finish_session(self, session_id, token, stopped):
        report = self.report()
        session = self._selected(report["sessions"], "session_id", session_id, token, stopped)
        if any(item["session_id"] == session_id for operation in report["operations"]
               for item in operation["document"]["items"]):
            raise FileManagementError("먼저 중단된 파일 작업을 확인하세요. / Review interrupted file operations first.")
        with ExitStack() as stack:
            self._hold_candidates(stack, [candidate for file in session["files"] for candidate in file["candidates"]])
            self.repo.finish_manual_review(session_id, session)
        log.warning("recovery.session_preserved_as_failed", extra={"session_id": session_id, "evidence": session})

    def acknowledge_operation(self, operation_id, token, stopped):
        operation = self._selected(self.report()["operations"], "operation_id", operation_id, token, stopped)
        document, updates = operation["document"], []
        with ExitStack() as stack:
            self._hold_candidates(stack, operation["evidence"])
            for item in document["items"]:
                if item["status"] in {"pending", "review"}:
                    item.update(status="acknowledged_unconfirmed", acknowledged_utc=utc_now(),
                                error="사용자가 결과 미확인으로 정리함. 파일 유지. / User acknowledged an unconfirmed result; files preserved.")
                    updates.append(self.files._update(item, item["source"], "unconfirmed"))
            document["manual_review"] = {"recorders_stopped_by_user": True, "evidence": operation["evidence"]}
            self.files._commit(operation_id, document, "acknowledged", updates)
        log.warning("recovery.operation_acknowledged", extra={"operation_id": operation_id, "document": document})
