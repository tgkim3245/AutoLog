"""Discard interrupted AutoLog work; completed outputs are never deleted."""

import logging
import os
import re
from pathlib import Path
from uuid import UUID

from vil_logging.contracts.models import Role, SessionPhase, utc_now
from vil_logging.storage.capture_files import cleanup_work_directory
from vil_logging.storage.file_access import ExclusiveFile, observe, plain_path

log = logging.getLogger(__name__)
HELPER = re.compile(r"\.AutoLog_finalize_[a-f0-9]{32}(?:_T[0-9]{1,20})*\.blf", re.I)


def _work_directory(session, file):
    identifier = session["session_id"]
    if str(UUID(identifier)) != identifier:
        raise ValueError("Invalid AutoLog session ID")
    source = Path(os.path.abspath(file["temp_path"]))
    expected = Path(os.path.abspath(file["final_path"])).parent / ".vil_work" / identifier
    if os.path.normcase(str(source.parent)) != os.path.normcase(str(expected)):
        raise ValueError("Working path is outside its reserved AutoLog session")
    if source.suffix.lower() not in {".blf", ".pcap", ".pcapng"}:
        raise ValueError("Unsupported working file")
    plain_path(expected)
    return source, expected


def discard_interrupted(repo, *, reason):
    results = []
    for session in repo.captures(limit=None, include_demo=True):
        pending = session["details"].get("interrupted_discard", {}).get("pending")
        if session["phase"] in {"completed", "failed"} and not pending:
            continue
        # Commit the new policy before deleting anything. A crash during cleanup
        # retries next startup without turning old captures into a start gate.
        repo.update_session(session["session_id"], SessionPhase.FAILED,
                            interrupted_discard={"reason": reason, "pending": True, "time_utc": utc_now()})
        errors, deleted = [], []
        for file in session["files"]:
            if file["state"] in {"published", "deleted", "not_created", "unconfirmed"}:
                continue
            try:
                source, directory = _work_directory(session, file)
                candidates = {source, source.with_name(source.name + ".sealed")}
                if directory.exists():
                    candidates.update(path for path in directory.iterdir() if HELPER.fullmatch(path.name))
                for path in sorted(candidates):
                    if not path.exists() and not path.is_symlink():
                        continue
                    with ExclusiveFile(path, observe(path)) as held:
                        held.delete()
                    deleted.append(str(path))
                cleanup_work_directory(directory)
            except (OSError, ValueError) as error:
                errors.append({"role": file["role"], "error": str(error)})
                repo.update_capture_file(session["session_id"], Role(file["role"]), "retained",
                                         discard_pending=True, error=str(error))
            else:
                repo.update_capture_file(session["session_id"], Role(file["role"]), "deleted",
                                         discard_pending=False, discarded_interrupted=True)
        result = {"session_id": session["session_id"], "reason": reason, "pending": bool(errors),
                  "deleted": deleted, "errors": errors, "time_utc": utc_now()}
        repo.update_session(session["session_id"], SessionPhase.FAILED, interrupted_discard=result)
        log.info("storage.interrupted_discarded", extra={"fields": result})
        results.append(result)
    return results
