"""Journalled management of published captures; never discovers arbitrary files."""

import logging
import os
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

from vil_logging.contracts.models import Role
from vil_logging.storage.file_access import ExclusiveFile, matches, observe
from vil_logging.storage.naming import renamed_filename
from vil_logging.storage.repository import Repository

log = logging.getLogger(__name__)


class FileManagementError(RuntimeError):
    pass


class FileResultStorageError(RuntimeError):
    """A filesystem change may have happened; preserve its pending journal."""


def _expected(file: dict) -> dict:
    metadata = file["metadata"]
    if value := metadata.get("file_identity"):
        return value
    inspected = metadata.get("inspection", {})
    return {key: inspected[key] for key in ("inode", "bytes", "mtime_ns") if key in inspected}


def _key(path):
    return os.path.normcase(os.path.abspath(path))


class FileService:
    def __init__(self, repository: Repository):
        self.repo = repository

    def history(self) -> list[dict]:
        renamed_names = {}
        for operation in self.repo.file_operations(limit=1000):
            if operation["kind"] != "rename":
                continue
            document = operation["document"]
            name = document.get("name", document.get("prefix", ""))
            for item in document.get("items", []):
                session_id = item.get("session_id")
                if session_id and session_id not in renamed_names:
                    renamed_names[session_id] = name if operation["status"] in {"completed", "recovered"} else ""
        unresolved = {(item["session_id"], item["role"]): item
                      for operation in self.repo.file_operations(unresolved=True)
                      for item in operation["document"]["items"] if item["status"] in {"pending", "review"}}
        result = []
        for session in self.repo.captures():
            view = {key: session[key] for key in ("session_id", "index", "prefix", "phase", "created_utc")}
            view["files"] = []
            for file in session["files"]:
                status, error, fingerprint = file["state"], "", {}
                path = file["metadata"].get("actual_path", file["final_path"])
                if (session["session_id"], file["role"]) in unresolved:
                    item = unresolved[session["session_id"], file["role"]]
                    status = "review"
                    error = ("중단된 파일 작업 / Interrupted file operation\n" + item["source"] +
                             ("\n→ " + item["destination"] if item.get("destination") else "") +
                             "\n" + item.get("error", ""))
                elif status == "published":
                    try:
                        fingerprint = observe(Path(path))
                        if not matches(fingerprint, _expected(file)):
                            status, error = "changed", "보관 후 파일이 바뀌었습니다. / File changed after capture."
                    except FileNotFoundError:
                        status, error = "missing", "파일이 없습니다. / File is missing."
                    except (OSError, ValueError) as exception:
                        status, error = "unavailable", str(exception)
                manageable = status == "published" and session["phase"] in {"completed", "failed"}
                view["files"].append({"session_id": session["session_id"], "role": file["role"],
                                       "path": path, "status": status, "error": error,
                                       "identity": fingerprint, "manageable": manageable})
            view["can_rename"] = bool(view["files"]) and all(file["manageable"] for file in view["files"])
            if session["session_id"] in renamed_names:
                view["current_name"] = renamed_names[session["session_id"]]
            else:
                view["current_name"] = session["prefix"]
            result.append(view)
        return result

    def _commit(self, identifier: str, document: dict, status: str, updates: list[dict]):
        try:
            self.repo.record_file_operation(identifier, document, status, updates)
        except Exception as error:
            log.exception("files.result_storage_failed", extra={"operation_id": identifier,
                                                               "document": document})
            raise FileResultStorageError("파일 결과 저장 실패. 재실행 후 작업 이력을 확인하세요. / "
                                         "File result persistence failed; review after restart.") from error

    @staticmethod
    def _status(document: dict) -> str:
        statuses = {item["status"] for item in document["items"]}
        if "review" in statuses:
            return "review"
        if "pending" in statuses:
            return "pending"
        if statuses <= {"renamed", "deleted", "unchanged", "recovered_rename"}:
            return "completed" if "recovered_rename" not in statuses else "recovered"
        if "acknowledged_unconfirmed" in statuses:
            return "acknowledged"
        return "partial" if statuses & {"renamed", "deleted", "recovered_rename"} else "blocked"

    @staticmethod
    def _update(item: dict, path: str, state: str = "published") -> dict:
        return {"session_id": item["session_id"], "role": item["role"], "actual_path": path,
                "state": state, "identity": item["identity"]}

    def rename_previous(self, session_id: str, name: str) -> dict:
        history = self.history()
        if not history or history[0]["session_id"] != session_id or not history[0]["can_rename"]:
            raise FileManagementError("직전 세션의 모든 파일이 보관 완료 상태여야 합니다. / "
                                      "Every file in the previous session must be published and available.")
        session = history[0]
        items = []
        for file in session["files"]:
            source = Path(file["path"])
            role = Role(file["role"])
            extension = source.suffix[1:]
            if extension not in ({"pcap", "pcapng"} if role == Role.ETHERNET else {"blf"}):
                raise FileManagementError("지원하지 않는 파일 확장자 / Unsupported capture extension")
            filename = renamed_filename(name, role, extension)
            destination = source.with_name(filename)
            if len(str(destination).encode("utf-16-le")) // 2 >= 260:
                raise ValueError(f"Capture path exceeds the supported Windows path length: {destination}")
            if str(source) != str(destination) and _key(source) == _key(destination):
                raise FileManagementError("대소문자만 바꾸려면 다른 prefix로 변경한 뒤 다시 변경하세요. / "
                                          "Use a different prefix first for a case-only rename.")
            self.repo.check_file_claims([str(source), str(destination)])
            if _key(source) != _key(destination) and (destination.exists() or destination.is_symlink()):
                raise FileExistsError(f"기존 파일을 보존합니다. / Existing output: {destination}")
            items.append({**file, "source": str(source), "destination": str(destination), "status": "pending"})
        identifier, document = uuid4().hex, {"name": name, "items": items}
        # Hold all source handles before persisting intent or making the first change.
        # A missing/used file therefore prevents the entire group from starting.
        with ExitStack() as stack:
            opened = [stack.enter_context(ExclusiveFile(Path(item["source"]), item["identity"])) for item in items]
            self.repo.begin_file_operation(identifier, "rename", document)
            for item, handle in zip(items, opened, strict=True):
                try:
                    if item["source"] == item["destination"]:
                        item.update(status="unchanged", actual_path=item["source"])
                    else:
                        handle.rename(Path(item["destination"]))
                        item.update(status="renamed", actual_path=item["destination"])
                except (OSError, ValueError) as error:
                    log.exception("files.rename_failed", extra={"operation_id": identifier, "item": item})
                    item.update(status="failed", actual_path=item["source"], error=str(error))
                self._commit(identifier, document, self._status(document),
                             [self._update(item, item["actual_path"])])
        return {"operation_id": identifier, "kind": "rename", "status": self._status(document), **document}

    def delete_selected(self, selected: list[dict]) -> dict:
        if not selected:
            raise FileManagementError("삭제할 파일을 선택하세요. / Select capture files to delete.")
        available = {(file["session_id"], file["role"]): file for session in self.history()
                     for file in session["files"]}
        items, seen = [], set()
        for requested in selected:
            key = (requested["session_id"], requested["role"])
            file = available.get(key)
            if (key in seen or not file or not file["manageable"] or file["path"] != requested["path"]
                    or file["identity"] != requested["identity"]):
                raise FileManagementError("확인한 파일과 현재 상태가 다릅니다. 목록을 새로 고치세요. / "
                                          "The confirmed selection changed. Refresh the file list.")
            seen.add(key)
            self.repo.check_file_claims([file["path"]])
            items.append({**file, "source": file["path"], "status": "pending"})
        identifier, document = uuid4().hex, {"items": items}
        self.repo.begin_file_operation(identifier, "delete", document)
        for item in items:
            try:
                with ExclusiveFile(Path(item["source"]), item["identity"]) as handle:
                    handle.delete()
                item.update(status="deleted", actual_path=item["source"])
            except (OSError, ValueError) as error:
                log.exception("files.delete_failed", extra={"operation_id": identifier, "item": item})
                item.update(status="failed", actual_path=item["source"], error=str(error))
            self._commit(identifier, document, self._status(document),
                         [self._update(item, item["actual_path"], "deleted" if item["status"] == "deleted" else "published")])
        return {"operation_id": identifier, "kind": "delete", "status": self._status(document), **document}

    def recover(self) -> list[dict]:
        """Observe only. Never repeat a rename/deletion or promote a capture."""
        recovered = []
        for operation in self.repo.file_operations(unresolved=True):
            document, updates = operation["document"], []
            for item in document["items"]:
                if item["status"] not in {"pending", "review"}:
                    continue
                evidence = {}
                for name in ("source", "destination"):
                    if not item.get(name):
                        continue
                    try:
                        evidence[name] = {"present": True, "identity": observe(Path(item[name]))}
                    except FileNotFoundError:
                        evidence[name] = {"present": False}
                    except (OSError, ValueError) as error:
                        evidence[name] = {"error": str(error)}
                item["recovery_evidence"] = evidence
                source = evidence["source"]
                destination = evidence.get("destination", {})
                same_source = matches(source.get("identity", {}), item["identity"])
                same_destination = matches(destination.get("identity", {}), item["identity"])
                if operation["kind"] in {"rename", "recover_publish"} and same_destination and source.get("present") is False:
                    item.update(status="recovered_rename", actual_path=item["destination"])
                    updates.append(self._update(item, item["destination"]))
                elif same_source and (operation["kind"] == "delete" or destination.get("present") is False
                                      or item["source"] == item.get("destination")):
                    item.update(status="not_applied", actual_path=item["source"])
                    if operation["kind"] != "recover_publish" or item["source"] == item.get("destination"):
                        updates.append(self._update(item, item["source"]))
                else:
                    # Absence cannot prove our delete was the cause. Keep both candidates.
                    item.update(status="review", error="파일 작업 결과 확인 불가 / File operation result unconfirmed")
            self._commit(operation["operation_id"], document, self._status(document), updates)
            recovered.append({**operation, "document": document, "status": self._status(document)})
        return recovered
