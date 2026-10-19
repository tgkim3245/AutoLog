"""Background coordinator for real CANoe/Ethernet and explicit simulation.

SQLite and worker pipes belong to one executor thread. UI callbacks only submit
requests and consume bounded notifications; they never wait for tool operations.
"""

import logging
import queue
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

from vil_logging.contracts.commands import FakeBehavior
from vil_logging.contracts.models import (
    AppEvent,
    AppSettings,
    CapturePlan,
    ConnectionState,
    ObservationState,
    RecordingState,
    Role,
    SessionPhase,
    TargetSnapshot,
    utc_now,
)
from vil_logging.diagnostics.capture_quality import LOW_SPACE_BYTES, SPACE_RECOVERY_BYTES
from vil_logging.monitors.observation import fresh_report
from vil_logging.storage.capture_files import cleanup_work_directory, publish_capture
from vil_logging.storage.file_access import matches, observe
from vil_logging.storage.file_service import FileResultStorageError, FileService
from vil_logging.storage.naming import build_plan, find_collisions, validate_settings
from vil_logging.storage.recovery import RecoveryService
from vil_logging.storage.repository import Repository
from vil_logging.workers.ethernet_pool import CaptureWorkerPool
from vil_logging.workers.pool import FakeWorkerPool

log = logging.getLogger(__name__)
ACTIVE = {
    SessionPhase.PREPARING, SessionPhase.STARTING, SessionPhase.RECORDING,
    SessionPhase.PARTIAL, SessionPhase.STOPPING,
}


class Runtime:
    def __init__(self, data_dir: Path, *, demo: bool = False,
                 behaviors: dict[Role, FakeBehavior] | None = None,
                 _verification_filter: str | None = None):
        self.data_dir = Path(data_dir)
        self.demo = demo
        self.messages: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=512)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="VIL-coordinator")
        self._diagnostics = ThreadPoolExecutor(max_workers=2, thread_name_prefix="VIL-readiness")
        self._lock = threading.RLock()
        self._phase = SessionPhase.IDLE
        self._cancel = threading.Event()
        self._repo: Repository | None = None
        self._settings: AppSettings | None = None
        self._pool = FakeWorkerPool(behaviors) if demo else CaptureWorkerPool()
        self._verification_filter = _verification_filter
        self._observation_loss_reported = False
        self._monitor_reports = {}
        self._monitor_counts = {}
        self._monitor_last_persist = 0
        self._quality_report = {}
        self._disk_warning = False
        self._plan: CapturePlan | None = None
        self._issued_roles: tuple[Role, ...] = ()
        self._published_files: dict[Role, dict] = {}
        self._snapshots = {role: TargetSnapshot(role) for role in Role}
        self._failure_latched = False
        self._target_failures: dict[Role, str] = {}
        self._storage_failed = False
        self._closed = False
        self._ready = False
        self._heartbeat: Future | None = None
        self._notification_loss = 0
        self._exit_pending = False
        self._file_busy = False
        self._file_service: FileService | None = None
        self._recovery: RecoveryService | None = None
        self._discovery_generation = 0
        self._connections: dict | None = None
        self._preparation_generations = {role: 0 for role in Role}

    def _background(self, operation, finished) -> Future:
        future = self._diagnostics.submit(operation)

        def completed(result):
            if not self._closed and not result.cancelled():
                self._submit(finished, result)

        future.add_done_callback(completed)
        return future

    @property
    def phase(self) -> SessionPhase:
        with self._lock:
            return self._phase

    def _publish(self, kind: str, value: Any) -> None:
        try:
            self.messages.put_nowait((kind, value))
        except queue.Full:
            self._notification_loss += 1
            log.error("ui.notification_overflow", extra={"fields": {"kind": kind}})

    def _event(self, code: str, *, level: str = "INFO", target: str = "app",
               original: str = "", **params: Any) -> None:
        event = AppEvent(code, level, target, params, original,
                         session_id=self._plan.session_id if self._plan else None)
        if self._repo is not None:
            try:
                self._repo.append_event(event)
            except Exception:
                self._storage_failed = True
                log.exception("event.persist_failed", extra={"event_code": code})
                self._publish("event", AppEvent(
                    "OPERATION_ERROR", "ERROR", original="Event history could not be saved",
                ))
        self._publish("event", event)
        log.log(getattr(logging, level, logging.INFO), code, extra={"fields": {
            "target": target, "params": params, "original": original,
            "session_id": event.session_id,
        }})

    def _set_phase(self, phase: SessionPhase) -> None:
        with self._lock:
            previous, self._phase = self._phase, phase
        log.info("session.phase", extra={"fields": {
            "previous": previous.value, "phase": phase.value,
            "session_id": self._plan.session_id if self._plan else None,
        }})
        self._publish("phase", phase)

    def _target(self, role: Role, **changes: Any) -> None:
        snapshot = replace(self._snapshots[role], **changes)
        self._snapshots[role] = snapshot
        self._publish("target", snapshot)
        log.debug("target.state", extra={"fields": {
            "role": role.value, "connection": snapshot.connection.value,
            "recording": snapshot.recording.value, "observation": snapshot.observation.value,
            "evidence": snapshot.evidence,
        }})

    def _submit(self, operation, *args, **kwargs) -> Future:
        def run():
            try:
                return operation(*args, **kwargs)
            except Exception as error:
                log.exception("operation.failed", extra={"operation": operation.__name__})
                self._event("OPERATION_ERROR", level="ERROR", original=str(error),
                            operation=operation.__name__)
                if self.phase in {SessionPhase.PREPARING, SessionPhase.STARTING,
                                  SessionPhase.STOPPING}:
                    # An unexpected exception cannot establish that external work stopped.
                    phase = SessionPhase.INCOMPLETE if self._plan else SessionPhase.FAILED
                    self._set_phase(phase)
                return None
        return self._executor.submit(run)

    def initialize(self) -> Future:
        return self._submit(self._initialize)

    def _initialize(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        default_output = self.data_dir / "captures"
        default_output.mkdir(exist_ok=True)
        self._repo = Repository(self.data_dir / "state.sqlite3")
        self._settings = self._repo.load_settings(str(default_output))
        self._file_service = FileService(self._repo)
        self._recovery = RecoveryService(self._repo)
        file_recovery = self._file_service.recover()
        recovered = self._repo.recover_incomplete()
        from vil_logging.storage.retention import maintain
        retention_notice = None
        try:
            retention = maintain(self._repo)
            log.info("history.retention", extra={"result": retention})
            if retention["status"] == "archived":
                retention_notice = {"code": "HISTORY_ARCHIVED", **retention}
        except Exception as error:
            log.exception("history.retention_failed")
            retention_notice = {"code": "HISTORY_ARCHIVE_FAILED", "level": "WARNING", "original": str(error)}
        self._publish("settings", self._settings)
        # Historical rows must not consume nearly the whole control-message
        # queue before the first GUI tick (500 history rows versus 512 slots).
        self._publish("events", self._repo.recent_events())
        if retention_notice:
            self._event(**retention_notice)
        for snapshot in self._snapshots.values():
            self._publish("target", snapshot)
        self._ready = True
        self._event("APP_READY", demo=self.demo, data_dir=str(self.data_dir))
        if self.demo:
            self._event("DEMO_NOTICE")
        if recovered:
            self._set_phase(SessionPhase.INCOMPLETE)
            recovered_paths = []
            for session in recovered:
                for file in session["files"]:
                    observed = []
                    for key in ("temp_path", "final_path"):
                        try:
                            if Path(file[key]).exists():
                                observed.append(file[key])
                        except OSError:
                            observed.append(file[key])
                    recovered_paths.extend(observed or [file["temp_path"]])
            self._publish("files", (recovered_paths, "incomplete"))
            self._event("SESSION_INCOMPLETE", level="WARNING", original=str(recovered),
                        count=len(recovered))
        else:
            self._set_phase(SessionPhase.IDLE)
        if file_recovery:
            self._event("FILE_OPERATIONS_RECOVERED", level="WARNING", results=file_recovery)
        self._refresh_file_history()
        if not self.demo:
            for capture in self._repo.captures():
                quality = capture.get("details", {}).get("capture_quality")
                if quality:
                    self._quality_report = {**quality, "state": "historical" if quality.get("state") == "archived" else "unknown"}
                    self._publish("capture_quality", dict(self._quality_report))
                    break

    def refresh_file_history(self) -> Future:
        return self._submit(self._refresh_file_history)

    def _refresh_file_history(self):
        history = self._file_service.history() if self._file_service and not self.demo else []
        self._publish("capture_history", history)
        self._publish("file_operations", self._repo.file_operations() if self._repo and not self.demo else [])
        self._refresh_recovery()
        if history and self.phase not in ACTIVE | {SessionPhase.INCOMPLETE}:
            latest = history[0]
            paths = [file["path"] for file in latest["files"] if file["status"] != "deleted"]
            self._publish("files", (paths, "completed" if latest["phase"] == "completed" else "failed"))
        return history

    def _refresh_recovery(self):
        if not self._recovery:
            return
        report = self._recovery.report()
        report["live_session_id"] = (self._plan.session_id if self._plan and
                                     self.phase == SessionPhase.INCOMPLETE else "")
        self._publish("recovery", report)
        return report

    def recover(self, request: dict) -> Future | None:
        with self._lock:
            if (not self._ready or self._file_busy or self._exit_pending or self._storage_failed
                    or self.phase in ACTIVE):
                self._publish("recovery_result", {"success": False, "error":
                    "기록 또는 다른 파일 처리가 끝난 뒤 다시 시도하세요. / Finish recording and file operations first."})
                return None
            self._file_busy = True
            self._publish("file_busy", True)
        return self._submit(self._recover, dict(request))

    def _recover(self, request):
        try:
            action = request.get("action")
            live = self._plan and self.phase == SessionPhase.INCOMPLETE
            if live:
                if action != "retry_stop":
                    raise ValueError("현재 기록의 정지를 먼저 다시 확인하세요. / Retry stop for the current capture first.")
                success = self._stop()
                result = {"success": success, "action": action}
            else:
                self._event("RECOVERY_STARTED", request=request)
                if action == "recheck":
                    self._file_service.recover()
                elif action == "publish":
                    self._recovery.publish(request["session_id"], request["role"], request["token"],
                                           request.get("stopped"), self._settings.tshark_path)
                elif action == "finish":
                    self._recovery.finish_session(request["session_id"], request["token"], request.get("stopped"))
                elif action == "acknowledge":
                    self._recovery.acknowledge_operation(request["operation_id"], request["token"], request.get("stopped"))
                else:
                    raise ValueError("Unknown recovery action")
                report = self._recovery.report()
                if self.phase == SessionPhase.INCOMPLETE and not any(
                        row["phase"] == "incomplete" for row in report["sessions"]):
                    self._set_phase(SessionPhase.IDLE)
                result = {"success": True, "action": action}
                self._event("RECOVERY_COMPLETED", action=action)
            self._publish("recovery_result", result)
            return result
        except Exception as error:
            if isinstance(error, FileResultStorageError):
                self._storage_failed = True
            log.exception("recovery.failed", extra={"request": request})
            self._event("RECOVERY_ERROR", level="ERROR", original=str(error), request=request)
            result = {"success": False, "error": str(error)}
            self._publish("recovery_result", result)
            return result
        finally:
            try:
                self._refresh_file_history()
            finally:
                with self._lock:
                    self._file_busy = False
                    self._publish("file_busy", False)

    def rename_previous(self, session_id: str, name: str) -> Future | None:
        return self._manage_files("rename", session_id, name)

    def delete_files(self, selection: list[dict]) -> Future | None:
        return self._manage_files("delete", selection)

    def _manage_files(self, kind: str, *args) -> Future | None:
        with self._lock:
            if (not self._ready or self.demo or self._file_busy or self._exit_pending
                    or self.phase in ACTIVE | {SessionPhase.INCOMPLETE} or self._storage_failed):
                self._publish("event", AppEvent("FILE_MANAGEMENT_ERROR", "WARNING",
                                               original="파일 상태 또는 기록 처리를 먼저 확인하세요. / File management is locked."))
                return None
            self._file_busy = True
            self._publish("file_busy", True)
        return self._submit(self._perform_file_operation, kind, args)

    def _perform_file_operation(self, kind: str, args: tuple):
        try:
            self._event("FILE_OPERATION_STARTED", kind=kind)
            result = (self._file_service.rename_previous(*args) if kind == "rename"
                      else self._file_service.delete_selected(*args))
            code = "FILE_OPERATION_COMPLETED" if result["status"] == "completed" else "FILE_OPERATION_PARTIAL"
            self._event(code, level="INFO" if result["status"] == "completed" else "WARNING",
                        kind=kind, result=result)
            self._publish("file_result", result)
            return result
        except Exception as error:
            if isinstance(error, FileResultStorageError):
                self._storage_failed = True
            log.exception("files.operation_failed", extra={"kind": kind})
            self._event("FILE_MANAGEMENT_ERROR", level="ERROR", original=str(error), kind=kind)
            self._publish("file_result", {"status": "error", "kind": kind, "error": str(error)})
            return None
        finally:
            try:
                self._refresh_file_history()
            finally:
                with self._lock:
                    self._file_busy = False
                    self._publish("file_busy", False)

    def save_settings(self, settings: AppSettings, roles: tuple[Role, ...]) -> Future:
        return self._submit(self._save_settings, settings, roles)

    def save_preferences(self, patch: dict[str, str]) -> Future:
        return self._submit(self._save_preferences, dict(patch))

    def _save_preferences(self, patch: dict[str, str]) -> None:
        if not self._ready or self._file_busy or self.phase in ACTIVE or self.phase == SessionPhase.INCOMPLETE:
            self._event("SETTINGS_ERROR", level="WARNING", original="기록 처리 중에는 설정을 바꿀 수 없습니다.")
            return
        try:
            previous = self._settings
            self._settings = self._repo.save_preferences(patch)
            self._publish("settings", self._settings)
            changed = [key for key in patch if getattr(previous, key) != getattr(self._settings, key)]
            if changed:
                self._event("PREFERENCES_SAVED", fields=changed)
            if any(key in changed for key in ("tshark_path", "nic_id")):
                self._begin_discovery()
            for role, prefix in ((Role.CAN, "can"), (Role.DIAG, "diag")):
                if any(key in changed for key in (prefix + "_cfg", prefix + "_logging_block", prefix + "_hardware_baseline")):
                    self._target(role, connection=ConnectionState.UNKNOWN, evidence="CANoe settings changed")
                    self._publish("preparation", self._preparation_report(
                        role, "attention", "설정이 변경됐습니다. 연결 확인을 다시 눌러주세요.",
                        "Settings changed. Check the connection again."))
        except Exception as error:
            log.exception("preferences.save_failed")
            self._event("SETTINGS_ERROR", level="ERROR", original=str(error))

    def apply_naming(self, draft: AppSettings, roles: tuple[Role, ...]) -> Future:
        return self._submit(self._apply_naming, draft, roles)

    def _apply_naming(self, draft: AppSettings, roles: tuple[Role, ...]) -> None:
        # File picker autosaves may already have advanced the settings version.
        # A naming edit never overwrites those independently remembered choices.
        latest = replace(self._settings, prefix=draft.prefix, next_index=draft.next_index)
        self._save_settings(latest, roles)

    def _save_settings(self, settings: AppSettings, roles: tuple[Role, ...]) -> None:
        if self.phase in ACTIVE or self.phase == SessionPhase.INCOMPLETE:
            self._event("SETTINGS_ERROR", level="ERROR", original="Session is active or unresolved")
            return
        try:
            self._settings = self._repo.save_settings(settings, roles)
        except Exception as error:
            log.exception("settings.rejected")
            self._event("SETTINGS_ERROR", level="ERROR", original=str(error))
            if self._settings:
                self._publish("settings", self._settings)
            return
        self._publish("settings", self._settings)
        self._event("SETTINGS_SAVED", next_index=str(self._settings.next_index))

    def prepare(self, role: Role) -> Future:
        log.info("connection.prepare_requested", extra={"role": role.value, "demo": self.demo})
        self._publish("preparation", self._preparation_report(
            role, "checking", "연결 준비 상태를 확인하고 있습니다…", "Checking connection readiness…"))
        return self._submit(self._prepare, role)

    def _prepare(self, role: Role) -> None:
        if not self._ready or self.phase in ACTIVE or self.phase == SessionPhase.INCOMPLETE:
            self._publish("preparation", self._preparation_report(
                role, "attention", "기록 종료와 미완료 상태를 먼저 확인하세요.",
                "Finish capture and resolve incomplete sessions first."))
            self._event("TARGET_ERROR", level="WARNING", target=role.label,
                        original="Session is busy or unresolved")
            return
        self._target(role, connection=ConnectionState.CONNECTING)
        if self.demo:
            result = self._pool.request((role,), "prepare", "prepare")[role]
            self._target(role, connection=ConnectionState.READY if result.success else ConnectionState.ERROR,
                         evidence=result.evidence)
            self._publish("preparation", self._preparation_report(
                role, "ready" if result.success else "error",
                "모의 연결 준비가 완료됐습니다. 실제 장비는 연결하지 않습니다." if result.success else result.evidence,
                "Simulation is ready. No real device is connected." if result.success else result.evidence))
            self._event("TARGET_READY" if result.success else "TARGET_ERROR", target=role.label,
                        original=result.evidence, demo=True)
            return
        self._preparation_generations[role] += 1
        generation = self._preparation_generations[role]
        settings = self._settings
        self._background(lambda: self._check_connection(role, settings),
                         lambda future: self._finish_prepare(role, settings, generation, future))

    @staticmethod
    def _preparation_report(role: Role, status: str, message_ko: str,
                            message_en: str, detail: str = "") -> dict:
        return {"role": role.value, "status": status, "message_ko": message_ko,
                "message_en": message_en, "detail": detail}

    def _prepare_canoe(self, role):
        result = self._request_real((role,), "connect", "connection-check",
                                    parameters={role: self._real_params(role)}, timeout=45)[role]
        details = result.details
        if result.success:
            block = details.get("selected_block", "")
            if block and not self._real_params(role)["logging_block"]:
                key = ("can" if role == Role.CAN else "diag") + "_logging_block"
                self._settings = self._repo.save_preferences({key: block})
                self._publish("settings", self._settings)
            from vil_logging.diagnostics.canoe_readiness import (
                option_history_text,
                readiness_stage,
                stage_guidance,
            )
            stage = readiness_stage(details)
            ready = stage == "segment_ready"
            ko, en = (stage_guidance(stage, language) for language in ("ko", "en"))
            detail_ko = ("기록 중에는 CANoe의 기존 로깅 버튼·파일 설정을 함께 조작하지 마세요. "
                         "AutoLog는 선택 블록의 경로·자동 번호 옵션을 구간 동안 적용하고 정지 후 복구합니다.") if block else ""
            detail_en = ("Avoid concurrent CANoe logging controls or filename edits. AutoLog temporarily manages "
                         "this block's path and filename options, then restores them after stop.") if block else ""
            detail_zh = ("记录期间请勿同时操作 CANoe 的记录控制或修改文件名。AutoLog 会临时管理此块的路径和文件名选项，停止后恢复。") if block else ""
            diagnostics = details.get("measurement_diagnostics", {})
            detail_ko = "\n".join(filter(None, (option_history_text(diagnostics, "ko"), detail_ko)))
            detail_en = "\n".join(filter(None, (option_history_text(diagnostics, "en"), detail_en)))
            detail_zh = "\n".join(filter(None, (option_history_text(diagnostics, "zh"), detail_zh)))
            detail = detail_ko if self._settings.language == "ko" else detail_en
            report = self._preparation_report(role, "ready" if ready else "attention", ko, en, detail)
            report.update(blocks=details.get("blocks", []), selected_block=block,
                          connected_cfg=details.get("cfg", ""), canoe_pid=details.get("canoe_pid", 0),
                          detail_ko=detail_ko, detail_en=detail_en, detail_zh=detail_zh, readiness_stage=stage,
                          hardware=details.get("hardware", {}), measurement_diagnostics=diagnostics,
                          message_zh=stage_guidance(stage, "zh"))
            if ready:
                report.update(next_action_ko="logging으로 구간 기록을 제어하세요. 기록 중에는 CANoe의 기존 로깅 버튼과 "
                              "파일 설정을 함께 조작하지 마세요.",
                              next_action_en="Control segments with logging. Avoid concurrent CANoe logging controls "
                              "or filename edits during recording.")
            else:
                report.update(next_action_ko="위 항목을 조치한 뒤 연결 확인을 다시 누르세요.",
                              next_action_en="Complete the steps above, then check the connection again.")
        else:
            issue = details.get("connection_issue", "")
            restart = issue == "restart_required"
            setup_failed = issue == "setup_failed"
            ko = ("기존 CANoe를 한 번 모두 종료해야 합니다. 작업을 저장하고 닫은 뒤 연결 확인을 다시 누르세요."
                  if restart else "CANoe 독립 연결을 자동 준비하지 못했습니다. 설치 설정 접근 오류를 확인하세요."
                  if setup_failed else "CANoe 연결에 실패했습니다. 상세 오류를 확인하세요.")
            en = ("Close existing CANoe windows once after saving your work, then check the connection again."
                  if restart else "Could not prepare independent CANoe connections automatically. Review setup access."
                  if setup_failed else "CANoe connection failed. Review the detailed error.")
            if restart:
                detail = ("AutoLog가 필요한 설정을 자동 적용하고 각 .cfg를 별도 CANoe 창으로 엽니다. 연결 방식 선택은 필요 없습니다."
                          if self._settings.language == "ko" else
                          "AutoLog will prepare the required mode and open each .cfg in its own CANoe instance automatically.")
            elif setup_failed:
                detail = ("CANoe 설치 설정을 읽거나 적용하지 못했습니다. 설정 파일: " if self._settings.language == "ko" else
                          "Could not read or apply the CANoe installation setting. Settings file: ") + details.get("settings_path", "")
            else:
                detail = result.evidence
            report = self._preparation_report(
                role, "attention" if restart else "error", ko, en, detail)
            if restart or setup_failed:
                report.update(diagnostic_detail=result.evidence, connection_issue=issue,
                              next_action_ko="모든 CANoe 창을 닫고 이 카드의 연결 확인을 다시 누르세요."
                              if restart else "버그리포트에 기록된 설치 설정 오류를 확인하세요.",
                              next_action_en="Close all CANoe windows and check this connection again."
                              if restart else "Review the installation error in the bug report.")
        self._target(role, connection=ConnectionState.READY if report["status"] == "ready" else
                     ConnectionState.ERROR if report["status"] == "error" else ConnectionState.UNKNOWN,
                     evidence=report["message_ko"] + "\n" + report["detail"])
        self._publish("preparation", report)
        self._event("TARGET_READY" if report["status"] == "ready" else "TARGET_ATTENTION" if report["status"] == "attention" else
                    "TARGET_ERROR", level="INFO" if result.success else "WARNING" if report["status"] == "attention" else "ERROR", target=role.label,
                    original=report["message_ko"], details=details, error=result.evidence if not result.success else "")

    @classmethod
    def _check_connection(cls, role: Role, settings: AppSettings) -> tuple[dict, dict | None]:
        def report(status, ko, en, detail=""):
            return cls._preparation_report(role, status, ko, en, detail)
        if role != Role.ETHERNET:
            configured = settings.can_cfg if role == Role.CAN else settings.diag_cfg
            if not configured:
                return report("attention", f"{role.label}에서 사용할 .cfg 파일을 먼저 선택하세요.",
                              f"Choose a .cfg file for {role.label} first."), None
            path = Path(configured)
            try:
                if path.suffix.lower() != ".cfg" or not path.is_file():
                    return report("error", "저장된 구성 파일을 찾을 수 없습니다. 파일을 다시 선택하세요.",
                                  "The saved configuration is unavailable. Choose the file again.", str(path)), None
                with path.open("rb") as source:
                    source.read(1)
            except OSError as error:
                return report("error", "구성 파일을 읽을 수 없습니다. 경로와 접근 권한을 확인하세요.",
                              "Cannot read the configuration. Check its location and access.", str(error)), None
            from vil_logging.diagnostics.environment import _discover_canoe
            canoe = _discover_canoe()
            if not canoe.get("executables"):
                return report("error", "CANoe 설치를 찾지 못했습니다. 시험 PC의 CANoe 설치를 확인하세요.",
                              "CANoe was not found. Check its installation on the test PC.", str(path)), None
            result = report("attention", "구성 파일과 CANoe 설치를 확인했습니다. 전용 CANoe 창을 연결합니다.",
                          "Configuration and CANoe found. Connecting a dedicated CANoe window.",
                          str(path.resolve()))
            result["canoe_preflight"] = True
            return result, None
        from vil_logging.diagnostics.connections import discover_connections
        connections = discover_connections(settings.tshark_path, settings.nic_id)
        tool = connections["tshark"]
        if tool["status"] != "ready":
            return report("error", tool["message_ko"], tool["message_en"], tool.get("detail", "")), connections
        if connections.get("npcap", {}).get("status") == "missing" and not any(
            item.get("capture_available") for item in connections.get("interfaces", [])
        ):
            result = report("attention", "TShark는 정상입니다. 실제 캡처에 필요한 Npcap 드라이버가 없습니다.",
                            "TShark works. The Npcap driver needed for live capture is missing.",
                            connections.get("interface_query_error", ""))
            result.update(next_action_ko="별도 설치 안내에 따라 Npcap을 준비한 뒤 설정창을 다시 열고 장비의 네트워크를 선택하세요.",
                          next_action_en="Follow your separate guide to install Npcap, then reopen Settings and select the device network.")
            return result, connections
        if not settings.nic_id:
            return report("attention", "차량에 연결된 네트워크를 위 목록에서 선택하세요.",
                          "Choose the network connected to the vehicle from the list above."), connections
        if connections.get("remembered_nic_missing"):
            return report("error", "지난번 네트워크를 찾을 수 없습니다. 연결을 확인하거나 다른 네트워크를 선택하세요.",
                          "The previous network is missing. Check the cable or choose another network."), connections
        selected = next((item for item in connections["interfaces"]
                         if item["id"] == connections.get("selected_nic_id")), None)
        if selected is None or not selected.get("capture_available"):
            return report("attention", "네트워크는 확인했지만 캡처 드라이버에서 조회하지 못했습니다. Npcap 설치를 확인하세요.",
                          "The network is visible to Windows but not the capture driver. Check Npcap installation.",
                          connections.get("interface_query_error", "")), connections
        if not all(Path(tool["path"]).with_name(name).is_file() for name in ("capinfos.exe", "dumpcap.exe")):
            return report("attention", "capinfos.exe 또는 dumpcap.exe가 없습니다. Wireshark 설치를 확인하세요.",
                          "The capinfos.exe or dumpcap.exe tool is missing. Check your Wireshark installation."), connections
        result = report("ready", f"{selected['name']} 캡처 준비를 확인했습니다. 패킷 기록은 시작하지 않았습니다.",
                      f"{selected['name']} is available for capture. Recording has not started.", tool["path"]), connections
        result[0].update(next_action_ko="메인에서 Zipy를 선택하고 logging을 누르면 선택한 네트워크 기록을 시작합니다.",
                         message_zh=f"{selected['name']} 已准备好采集，尚未开始记录。",
                         next_action_en="Select Zipy on the main screen and press logging to capture the selected network.")
        return result

    def _finish_prepare(self, role: Role, captured: AppSettings, generation: int, future: Future) -> None:
        if self._closed or generation != self._preparation_generations[role]:
            return
        try:
            report, connections = future.result()
        except Exception as error:
            log.exception("connection.prepare_failed")
            report, connections = self._preparation_report(
                role, "error", "연결 확인 중 오류가 발생했습니다. 상세 내용을 확인한 뒤 다시 시도하세요.",
                "Readiness check failed. Review the details and try again.", str(error)), None
        if role == Role.ETHERNET:
            changed = captured.nic_id != self._settings.nic_id or (
                captured.tshark_path != self._settings.tshark_path and not (
                    not captured.tshark_path and connections and
                    connections["tshark"].get("path") == self._settings.tshark_path))
        else:
            key = "can_cfg" if role == Role.CAN else "diag_cfg"
            block_key = ("can" if role == Role.CAN else "diag") + "_logging_block"
            changed = (getattr(captured, key) != getattr(self._settings, key) or
                       getattr(captured, block_key) != getattr(self._settings, block_key))
        if changed:
            report = self._preparation_report(role, "attention", "설정이 변경됐습니다. 연결 준비를 다시 눌러주세요.",
                                               "Settings changed. Check readiness again.")
        elif role != Role.ETHERNET and report.get("canoe_preflight"):
            self._prepare_canoe(role)
            return
        elif connections is not None:
            self._accept_discovery(connections)
        log.info("connection.prepare_completed", extra={"report": report, "settings_changed": changed,
                                                        "generation": generation})
        connection = {"ready": ConnectionState.READY, "error": ConnectionState.ERROR}.get(
            report["status"], ConnectionState.UNKNOWN)
        self._target(role, connection=connection, evidence=report["message_ko"] + "\n" + report["detail"])
        self._publish("preparation", report)
        self._event({"ready": "TARGET_READY", "attention": "TARGET_ATTENTION"}.get(report["status"], "TARGET_ERROR"),
                    level="ERROR" if report["status"] == "error" else "INFO", target=role.label,
                    original=report["message_ko"], detail=report["detail"], readiness_only=True)

    def discover(self) -> Future:
        return self._submit(self._begin_discovery)

    def _begin_discovery(self) -> None:
        if self._closed or not self._ready:
            return
        from vil_logging.diagnostics.connections import discover_connections
        self._discovery_generation += 1
        generation, settings = self._discovery_generation, self._settings
        self._publish("discovery_busy", True)
        self._background(lambda: discover_connections(settings.tshark_path, settings.nic_id),
                         lambda future: self._finish_discovery(generation, settings, future))

    def _finish_discovery(self, generation: int, captured: AppSettings, future: Future) -> None:
        if self._closed or generation != self._discovery_generation:
            return
        self._publish("discovery_busy", False)
        if (captured.tshark_path, captured.nic_id) != (self._settings.tshark_path, self._settings.nic_id):
            return
        try:
            self._accept_discovery(future.result())
        except Exception as error:
            log.exception("connections.discovery_failed")
            self._publish("discovery_error", "캡처 도구와 네트워크를 찾는 중 오류가 발생했습니다. " + str(error))
            self._event("OPERATION_ERROR", level="ERROR", original=str(error))

    def _accept_discovery(self, report: dict) -> None:
        self._connections = report
        self._publish("connections", report)

    def toggle(self, roles: tuple[Role, ...]) -> Future | None:
        with self._lock:
            if self._file_busy:
                return None
            phase = self._phase
            if not self._ready:
                self._publish("event", AppEvent("OPERATION_ERROR", "WARNING",
                                               original="Application is initializing"))
                return None
            if phase in {SessionPhase.PREPARING, SessionPhase.STARTING}:
                self._cancel.set()
                log.info("session.cancel_requested")
                return None
            if phase in {SessionPhase.RECORDING, SessionPhase.PARTIAL}:
                self._phase = SessionPhase.STOPPING
                self._publish("phase", SessionPhase.STOPPING)
                return self._submit(self._stop)
            if phase in {SessionPhase.STOPPING, SessionPhase.INCOMPLETE} or self._exit_pending:
                return None
            self._cancel.clear()
            self._phase = SessionPhase.PREPARING
            self._publish("phase", SessionPhase.PREPARING)
            return self._submit(self._start, roles)

    def _start(self, roles: tuple[Role, ...]) -> None:
        self._plan = None
        self._issued_roles = ()
        self._published_files = {}
        self._failure_latched = False
        self._target_failures = {}
        self._monitor_reports = {}
        self._monitor_counts = {}
        self._monitor_last_persist = 0
        self._quality_report = {}
        self._disk_warning = False
        self._publish("capture_quality", {})
        for role in Role:
            self._target(role, observation=ObservationState.NOT_MONITORED, observation_details={})
        try:
            if not roles:
                self._event("NO_TARGETS", level="WARNING")
                self._set_phase(SessionPhase.IDLE)
                return
            if not self.demo:
                self._start_real(roles)
                return
            if self._storage_failed:
                raise RuntimeError("Persistent history failed; restart after resolving storage errors")
            self._event("SESSION_PREPARING")
            validate_settings(self._settings, roles)
            plan = build_plan(self._settings, roles, demo=True)
            if collisions := find_collisions(plan):
                raise RuntimeError("Output collision: " + ", ".join(map(str, collisions)))
            prepared = self._pool.request(roles, "prepare", plan.session_id, cancel=self._cancel)
            for role, result in prepared.items():
                self._target(role, connection=ConnectionState.READY if result.success else ConnectionState.ERROR,
                             evidence=result.evidence)
            if self._cancel.is_set():
                self._set_phase(SessionPhase.IDLE)
                self._event("SESSION_FAILED", level="WARNING", original="Cancelled before reservation")
                return
            if not all(result.success for result in prepared.values()):
                raise RuntimeError("Demo target preparation failed")
            self._settings = self._repo.reserve(plan)
            self._plan = plan
            self._publish("settings", self._settings)
            self._publish("files", ([file.filename for file in plan.files], "demo_files"))
            self._set_phase(SessionPhase.STARTING)
            self._repo.update_session(plan.session_id, SessionPhase.STARTING)
            self._event("SESSION_STARTING", index=str(plan.index), demo=True)
            issued: list[Role] = []
            if self._cancel.is_set():
                self._failure_latched = True
                self._stop(())
                return
            groups = [(Role.ETHERNET,)] if Role.ETHERNET in roles else []
            can_roles = tuple(role for role in roles if role != Role.ETHERNET)
            if can_roles:
                groups.append(can_roles)
            for group in groups:
                issued.extend(group)
                self._issued_roles = tuple(issued)
                for role in group:
                    self._target(role, recording=RecordingState.STARTING)
                results = self._pool.request(group, "start", plan.session_id, cancel=self._cancel)
                for role, result in results.items():
                    if not result.success and not self._cancel.is_set():
                        self._target_failures[role] = result.evidence
                    self._target(role, recording=RecordingState.RECORDING if result.success
                                 else RecordingState.UNKNOWN, evidence=result.evidence,
                                 observation=ObservationState.NOT_CONFIGURED if result.success
                                 else ObservationState.NOT_MONITORED)
                if self._cancel.is_set() or not all(result.success for result in results.values()):
                    self._failure_latched = True
                    self._event("SESSION_FAILED", level="ERROR", original="Start failed or cancelled")
                    self._stop(tuple(issued))
                    return
            self._repo.update_session(plan.session_id, SessionPhase.RECORDING)
            # The user may request cancellation while the commit is pending.
            # Decide under the same short lock used by toggle; never hold it for DB I/O.
            with self._lock:
                cancelled = self._cancel.is_set()
                if not cancelled:
                    self._set_phase(SessionPhase.RECORDING)
            if cancelled:
                self._failure_latched = True
                self._stop(tuple(issued))
                return
            self._event("SESSION_RECORDING", demo=True)
        except Exception as error:
            log.exception("session.start_failed")
            self._event("SESSION_FAILED", level="ERROR", original=str(error))
            if self._plan is not None:
                self._failure_latched = True
                # Some Start calls might have been sent before an unexpected failure.
                self._stop()
            else:
                self._set_phase(SessionPhase.FAILED)

    def _stop(self, roles: tuple[Role, ...] | None = None) -> bool:
        if self._plan is None:
            self._set_phase(SessionPhase.IDLE)
            return True
        plan = self._plan
        if not self.demo:
            return self._stop_real(roles)
        selected = roles if roles is not None else self._issued_roles
        self._set_phase(SessionPhase.STOPPING)
        self._event("SESSION_STOPPING")
        for role in selected:
            self._target(role, recording=RecordingState.STOPPING)
        results = self._pool.request(selected, "stop", plan.session_id, timeout=3.0)
        confirmed = True
        for role, result in results.items():
            stopped = result.success and result.state == "stopped"
            confirmed &= stopped
            failure = self._target_failures.get(role)
            state = (RecordingState.ERROR if failure else RecordingState.STOPPED
                     ) if stopped else RecordingState.UNKNOWN
            evidence = f"Previous error: {failure}; stop evidence: {result.evidence}" if failure else result.evidence
            self._target(role, recording=state, observation=ObservationState.NOT_MONITORED,
                         evidence=evidence)
        phase = (SessionPhase.FAILED if self._failure_latched else SessionPhase.COMPLETED
                 ) if confirmed else SessionPhase.INCOMPLETE
        try:
            self._repo.update_session(plan.session_id, phase, demo=True, capture_files_created=False,
                                      results={role.value: {"success": result.success, "state": result.state,
                                                           "evidence": result.evidence}
                                               for role, result in results.items()})
        except Exception as error:
            self._storage_failed = True
            phase = SessionPhase.INCOMPLETE
            log.exception("session.final_state_save_failed")
            self._event("OPERATION_ERROR", level="ERROR", original=str(error))
        self._set_phase(phase)
        self._publish("files", ([file.filename for file in plan.files], "demo_files"))
        self._event("SESSION_" + phase.value.upper(), level="INFO" if phase == SessionPhase.COMPLETED
                    else "WARNING", demo=True, files_created=False)
        return phase != SessionPhase.INCOMPLETE

    def poll_workers(self) -> None:
        if self.phase not in {SessionPhase.RECORDING, SessionPhase.PARTIAL}:
            return
        if self._heartbeat is None or self._heartbeat.done():
            self._heartbeat = self._submit(self._query)

    def _query(self) -> None:
        if self.phase not in {SessionPhase.RECORDING, SessionPhase.PARTIAL} or not self._plan:
            return
        results = self._pool.request(self._plan.roles, "query", self._plan.session_id,
                                      timeout=1.5 if any(role != Role.ETHERNET for role in self._plan.roles) else 0.6)
        any_recording = False
        for role, result in results.items():
            if result.success and result.state == "recording":
                any_recording = True
                if not self.demo:
                    details = result.details
                    self._accept_monitor(role, details)
                    if role == Role.ETHERNET:
                        self._accept_quality(details)
                    if details.get("summary_drops", 0) and not self._observation_loss_reported:
                        self._observation_loss_reported = True
                        self._event("DISPLAY_SUMMARY_LOSS", level="WARNING", target=role.label,
                                    count=details["summary_drops"])
                continue
            previous = self._snapshots[role].recording
            state = RecordingState.ERROR if result.state in {"error", "stopped"} else RecordingState.UNKNOWN
            self._target(role, recording=state, observation=ObservationState.UNKNOWN,
                         evidence=result.evidence, observation_details={"status": "unknown", "reasons": ["recorder_unavailable"]})
            self._monitor_reports[role.value] = {"status": "unknown", "rules": [], "reasons": ["recorder_unavailable"]}
            if role == Role.ETHERNET:
                self._quality_report = {**self._quality_report, "state": "unknown", "error": result.evidence}
                self._publish("capture_quality", dict(self._quality_report))
            if previous != state:
                self._failure_latched = True
                self._target_failures[role] = result.evidence
                self._event("TARGET_ERROR", level="ERROR", target=role.label, original=result.evidence)
        if self._failure_latched:
            # A UI Stop may already be queued; never overwrite its STOPPING phase.
            if self.phase in {SessionPhase.RECORDING, SessionPhase.PARTIAL}:
                self._set_phase(SessionPhase.PARTIAL)
                self._repo.update_session(self._plan.session_id, SessionPhase.PARTIAL)
            if not any_recording and all(result.state in {"error", "stopped"} for result in results.values()):
                self._stop()
        self._persist_monitors()

    def _accept_monitor(self, role, details, *, stopped=False):
        if role != Role.ETHERNET:
            report = {"status": "unsupported", "rules": [], "reasons": ["canoe_receive_events_unavailable"]}
        else:
            report = details.get("monitor")
            if (not isinstance(report, dict) or report.get("session_id") != self._plan.session_id
                    or report.get("status") not in ({"not_monitored"} if stopped else set()) |
                    {"not_configured", "unknown", "normal", "warning"}):
                report = {"status": "unknown", "rules": [], "reasons": ["observation_unavailable"]}
            else:
                report = fresh_report(dict(report)) if not stopped else dict(report)
            report["parsed_packets"] = details.get("parsed_packets", 0)
            report["display_drops"] = details.get("summary_drops", 0)
            report["parse_errors"] = details.get("parse_errors", 0)
            report["reader_errors"] = details.get("reader_errors", [])
            report["last_packet_utc"] = details.get("last_packet_utc")
        previous = self._monitor_reports.get(role.value, {})
        for row in report.get("rules", []):
            for key, event in (("missing", "MONITOR_MISSING"), ("source", "MONITOR_SOURCE"),
                               ("recovered", "MONITOR_RECOVERED")):
                counter_key = (role.value, row["id"], key)
                count = row["counters"].get(key, 0)
                delta = count - self._monitor_counts.get(counter_key, 0)
                if delta > 0:
                    self._event(event, level="INFO" if key == "recovered" else "WARNING", target=role.label,
                                rule=row["name"], episodes=delta, total_episodes=count, evidence=row)
                self._monitor_counts[counter_key] = count
        def issues(value):
            return sorted(set(value.get("reasons", [])) | {reason for row in value.get("rules", [])
                          for reason in row["reasons"] if reason not in {"waiting_samples", "missing_flow", "unexpected_source"}})
        current_issues, previous_issues = issues(report), issues(previous)
        if report["status"] == "unknown" and current_issues and current_issues != previous_issues:
            self._event("MONITOR_UNCONFIRMED", level="WARNING", target=role.label, reasons=current_issues)
        elif previous.get("status") == "unknown" and previous_issues and report["status"] in {"normal", "warning"}:
            self._event("MONITOR_OBSERVATION_RESTORED", target=role.label)
        elif report["status"] in {"unsupported", "not_configured"} and previous.get("status") != report["status"]:
            self._event("MONITOR_" + report["status"].upper(), target=role.label)
        if stopped:
            report["status"] = "not_monitored"
        report["updated_utc"] = utc_now()
        self._monitor_reports[role.value] = report
        self._target(role, observation=ObservationState(report["status"]), observation_details=report)

    def _persist_monitors(self):
        if self._plan and self._monitor_reports and time.monotonic() - self._monitor_last_persist >= 5:
            self._repo.update_session(self._plan.session_id, self.phase, monitoring=dict(self._monitor_reports),
                                      capture_quality=dict(self._quality_report))
            log.info("capture.quality_sample", extra={"fields": dict(self._quality_report)})
            self._monitor_last_persist = time.monotonic()

    def _accept_quality(self, details, *, closed=False, path=None):
        if not self._plan or details.get("session_id") != self._plan.session_id:
            return
        metrics = details.get("performance", {})
        loss = details.get("capture_loss", {"status": "unknown", "reason": "capture_in_progress"})
        report = {"session_id": self._plan.session_id, "state": "archived" if closed else "recording",
                  "metrics": metrics, "capture_loss": loss, "parsed_packets": details.get("parsed_packets", 0),
                  "display_drops": details.get("summary_drops", 0), "parse_errors": details.get("parse_errors", 0),
                  "reader_errors": details.get("reader_errors", []), "binding": details.get("binding", {}),
                  "packet_count": details.get("packet_count"), "summary_consistency": details.get("summary_consistency"),
                  "path": str(path or details.get("temp_path", "")), "sampled_epoch": metrics.get("sampled_epoch")}
        free = metrics.get("disk_free_bytes")
        if free is not None and free <= LOW_SPACE_BYTES and not self._disk_warning:
            self._disk_warning = True
            self._event("DISK_SPACE_LOW", level="WARNING", free_bytes=free, path=report["path"])
        elif self._disk_warning and free is not None and free > SPACE_RECOVERY_BYTES:
            self._disk_warning = False
            self._event("DISK_SPACE_RESTORED", free_bytes=free)
        if closed and loss.get("status") == "loss_reported":
            self._event("CAPTURE_DROP_REPORTED", level="WARNING", counters=loss)
        if closed and report["summary_consistency"] and not report["summary_consistency"]["same_count"]:
            self._event("CAPTURE_SUMMARY_MISMATCH", level="WARNING", evidence=report["summary_consistency"])
        self._quality_report = report
        self._publish("capture_quality", report)
        if closed:
            log.info("capture.quality_final", extra={"fields": report})

    def _quality_unknown(self, error):
        if self._quality_report:
            self._quality_report = {**self._quality_report, "state": "unknown", "error": str(error)}
            self._publish("capture_quality", dict(self._quality_report))

    def drain_packets(self):
        packets = self._pool.drain_packets() if self._pool is not None else []
        return [packet for packet in packets if not self._plan or packet.session_id == self._plan.session_id]

    def _real_params(self, role: Role) -> dict:
        if role == Role.ETHERNET:
            return {"tshark_path": self._settings.tshark_path, "nic_id": self._settings.nic_id,
                    "file_format": self._settings.ethernet_format, "buffer_mib": "64"}
        key = "can" if role == Role.CAN else "diag"
        return {"cfg_path": getattr(self._settings, key + "_cfg"),
                "logging_block": getattr(self._settings, key + "_logging_block"),
                "hardware_baseline": getattr(self._settings, key + "_hardware_baseline")}

    def _request_real(self, roles, action, session_id, parameters=None, **kwargs):
        parameters = parameters or {}
        return self._pool.request(roles, action, session_id, role_params=parameters,
                                  params=parameters.get(roles[0], {}) if len(roles) == 1 else {},
                                  **kwargs)

    def _restore_canoe_outputs(self, roles, session_id):
        if not roles:
            return
        try:
            results = self._request_real(roles, "restore", session_id, timeout=15)
        except Exception as error:
            log.exception("canoe.output_restore_request_failed")
            self._event("OPERATION_ERROR", level="WARNING", original=str(error), roles=[r.value for r in roles])
            return
        for role, result in results.items():
            if not result.success:
                self._event("OPERATION_ERROR", level="WARNING", target=role.label,
                            original="CANoe 출력 설정 복구를 확인하지 못했습니다. 다음 연결에서 다시 확인합니다. " + result.evidence,
                            details=result.details)

    def _start_real(self, roles: tuple[Role, ...]) -> None:
        if self._storage_failed:
            raise RuntimeError("Persistent history failed; resolve storage errors before capture")
        if Role.CAN in roles and Role.DIAG in roles:
            if Path(self._settings.can_cfg).resolve() == Path(self._settings.diag_cfg).resolve():
                raise ValueError("CAN and Diag require distinct .cfg files for independent control.")
        self._event("SESSION_PREPARING")
        validate_settings(self._settings, roles)
        plan = build_plan(self._settings, roles)
        self._repo.check_file_claims([str(file.final_path) for file in plan.files])
        if collisions := find_collisions(plan):
            raise FileExistsError("Existing outputs are preserved: " + ", ".join(map(str, collisions)))
        prepared = self._request_real(roles, "prepare", plan.session_id, timeout=45, cancel=self._cancel,
                                      parameters={role: self._real_params(role) for role in roles})
        for role, result in prepared.items():
            self._target(role, connection=ConnectionState.READY if result.success else ConnectionState.ERROR,
                         evidence=result.evidence)
        if self._cancel.is_set():
            self._set_phase(SessionPhase.IDLE)
            self._event("SESSION_CANCELLED", level="WARNING", reserved=False)
            return
        failures = [f"{role.label}: {result.evidence}" for role, result in prepared.items() if not result.success]
        if failures:
            raise RuntimeError("\n".join(failures))
        session_dir = plan.files[0].temp_path.parent
        session_dir.mkdir(parents=True, exist_ok=False)
        try:
            can_roles = tuple(role for role in roles if role != Role.ETHERNET)
            if can_roles:
                configured = self._request_real(
                    can_roles, "configure", plan.session_id, timeout=15, cancel=self._cancel,
                    parameters={file.role: {"temp_path": str(file.temp_path)} for file in plan.files})
                failures = [f"{role.label}: {result.evidence}" for role, result in configured.items()
                            if not result.success]
                if failures:
                    raise RuntimeError("\n".join(failures))
            if self._cancel.is_set():
                self._restore_canoe_outputs(can_roles, plan.session_id)
                cleanup_work_directory(session_dir)
                self._set_phase(SessionPhase.IDLE)
                self._event("SESSION_CANCELLED", level="WARNING", reserved=False)
                return
            self._settings = self._repo.reserve(plan)
        except Exception:
            self._restore_canoe_outputs(can_roles, plan.session_id)
            cleanup_work_directory(session_dir)  # Only empty directories; never remove partial data.
            raise
        self._plan = plan
        self._observation_loss_reported = False
        self._publish("settings", self._settings)
        self._publish("packets_clear", None)
        self._publish("files", ([str(file.temp_path) for file in plan.files], "recording"))
        self._set_phase(SessionPhase.STARTING)
        self._repo.update_session(plan.session_id, SessionPhase.STARTING,
                                  tool_binding={role.value: result.details for role, result in prepared.items()})
        self._event("SESSION_STARTING", index=str(plan.index), demo=False)
        if self._cancel.is_set():
            self._failure_latched = True
            self._stop_real(())
            return
        groups = [(Role.ETHERNET,)] if Role.ETHERNET in roles else []
        if can_group := tuple(role for role in roles if role != Role.ETHERNET):
            groups.append(can_group)
        for group in groups:
            if self._cancel.is_set():
                self._failure_latched = True
                self._stop_real()
                return
            self._issued_roles += group  # Intent precedes COM/pipe calls, including timeouts.
            for role in group:
                self._target(role, recording=RecordingState.STARTING)
            parameters = {file.role: {"temp_path": str(file.temp_path)} for file in plan.files}
            if Role.ETHERNET in group:
                parameters[Role.ETHERNET]["monitor_rules_json"] = self._settings.monitor_rules_json
            if self._verification_filter and Role.ETHERNET in group:
                parameters[Role.ETHERNET]["verification_filter"] = self._verification_filter
            results = self._request_real(group, "start", plan.session_id, timeout=18, cancel=self._cancel,
                                         parameters=parameters)
            for role, result in results.items():
                self._target(role, recording=RecordingState.RECORDING if result.success else RecordingState.UNKNOWN,
                             observation=ObservationState.NOT_CONFIGURED, evidence=result.evidence)
                if not result.success:
                    self._target_failures[role] = result.evidence
                else:
                    self._accept_monitor(role, result.details)
                    if role == Role.ETHERNET:
                        self._accept_quality(result.details)
                    file = next(file for file in plan.files if file.role == role)
                    self._repo.update_capture_file(plan.session_id, role, "writing",
                                                   actual_path=str(file.temp_path), start_evidence=result.details)
            if self._cancel.is_set() or not all(result.success for result in results.values()):
                self._failure_latched = True
                self._stop_real()
                return
        self._repo.update_session(plan.session_id, SessionPhase.RECORDING)
        with self._lock:
            cancelled = self._cancel.is_set()
            if not cancelled:
                self._set_phase(SessionPhase.RECORDING)
        if cancelled:
            self._failure_latched = True
            self._stop_real()
            return
        self._event("SESSION_RECORDING", demo=False)

    def _stop_real(self, roles: tuple[Role, ...] | None = None) -> bool:
        plan = self._plan
        selected = self._issued_roles if roles is None else roles
        self._set_phase(SessionPhase.STOPPING)
        self._event("SESSION_STOPPING")
        for role in selected:
            self._target(role, recording=RecordingState.STOPPING)
        # Send all stops before waiting, so a stalled COM target cannot suppress the others.
        results = self._pool.request(selected, "stop", plan.session_id, timeout=35)
        self._restore_canoe_outputs(tuple(file.role for file in plan.files
                                         if file.role != Role.ETHERNET and file.role not in selected), plan.session_id)
        for role, result in results.items():
            if result.details.get("output_restore_error"):
                self._event("OPERATION_ERROR", level="WARNING", target=role.label,
                            original="BLF는 닫혔지만 CANoe 출력 설정 복구가 필요합니다: " +
                                     result.details["output_restore_error"], details=result.details)
        confirmed = all(result.success and result.state == "stopped" for result in results.values())
        phase = (SessionPhase.FAILED if self._failure_latched else SessionPhase.COMPLETED
                 ) if confirmed else SessionPhase.INCOMPLETE
        actual_paths = []
        inspections = {role.value: inspection for role, inspection in self._published_files.items()}
        try:
            for file in plan.files:
                role, actual_path = file.role, file.temp_path
                stopped = role not in selected or (results[role].success and results[role].state == "stopped")
                self._target(role, recording=(RecordingState.ERROR if role in self._target_failures else
                                              RecordingState.STOPPED) if stopped else RecordingState.UNKNOWN,
                             observation=ObservationState.NOT_MONITORED if stopped else ObservationState.UNKNOWN,
                             evidence=self._target_failures.get(role, "Normal stop confirmed") if stopped else
                                      results[role].evidence)
                if role in results and stopped:
                    self._accept_monitor(role, results[role].details, stopped=stopped)
                elif not stopped:
                    report = {"status": "unknown", "reasons": ["recorder_unavailable"], "rules": []}
                    self._monitor_reports[role.value] = report
                    self._target(role, observation=ObservationState.UNKNOWN, observation_details=report)
                if role in self._published_files:
                    # A previous stop attempt may have archived this target while
                    # another target remained unresolved. Its working file is gone
                    # by design: keep the committed result and original inspection.
                    actual_path = file.final_path
                    expected = {key: self._published_files[role][key]
                                for key in ("inode", "bytes", "mtime_ns")}
                    try:
                        if not matches(observe(actual_path), expected):
                            raise ValueError("Published capture changed while retrying stop")
                    except (OSError, ValueError) as error:
                        if phase != SessionPhase.INCOMPLETE:
                            phase = SessionPhase.FAILED
                        self._event("FILE_ERROR", level="ERROR", target=role.label,
                                    original=str(error), path=str(actual_path))
                elif not stopped:
                    self._repo.update_capture_file(plan.session_id, role, "unknown", actual_path=str(actual_path))
                elif not file.temp_path.exists():
                    if phase != SessionPhase.INCOMPLETE:
                        phase = SessionPhase.FAILED
                    self._repo.update_capture_file(plan.session_id, role, "not_created")
                else:
                    self._repo.update_capture_file(plan.session_id, role, "closed", actual_path=str(actual_path))
                    self._event("FILE_CHECKING", target=role.label, path=str(actual_path))
                    checked = self._pool.request((role,), "inspect", plan.session_id,
                                                 timeout=120 if role != Role.ETHERNET else 65)[role]
                    if not checked.success:
                        if phase != SessionPhase.INCOMPLETE:
                            phase = SessionPhase.FAILED
                        self._repo.update_capture_file(plan.session_id, role, "failed",
                                                       actual_path=str(actual_path), error=checked.evidence)
                        self._event("FILE_ERROR", level="ERROR", target=role.label,
                                    original=checked.evidence, path=str(actual_path))
                    else:
                        inspection = checked.details
                        inspections[role.value] = inspection
                        self._repo.update_capture_file(plan.session_id, role, "publishing",
                                                       actual_path=str(actual_path), inspection=inspection)
                        try:
                            actual_path = publish_capture(file, inspection)
                        except (OSError, ValueError) as error:
                            if phase != SessionPhase.INCOMPLETE:
                                phase = SessionPhase.FAILED
                            self._repo.update_capture_file(plan.session_id, role, "failed",
                                                           actual_path=str(file.temp_path), error=str(error))
                            self._event("FILE_ERROR", level="ERROR", target=role.label,
                                        original=str(error), path=str(file.temp_path))
                        else:
                            self._repo.update_capture_file(plan.session_id, role, "published",
                                                           actual_path=str(actual_path), inspection=inspection)
                            self._published_files[role] = inspection
                            self._event("FILE_PUBLISHED" if role == Role.ETHERNET else "BLF_PUBLISHED",
                                        target=role.label, path=str(actual_path), bytes=inspection["bytes"],
                                        packets=inspection.get("packet_count", 0),
                                        objects=inspection.get("object_count", 0))
                            if role == Role.ETHERNET:
                                self._accept_quality(inspection, closed=True, path=actual_path)
                        if inspection.get("parse_errors") or inspection.get("reader_errors"):
                            self._event("OBSERVATION_LOSS", level="WARNING", target=role.label, counters=inspection)
                        if inspection.get("summary_drops") and not self._observation_loss_reported:
                            self._observation_loss_reported = True
                            self._event("DISPLAY_SUMMARY_LOSS", level="WARNING", target=role.label,
                                        count=inspection["summary_drops"])
                actual_paths.append(str(actual_path))
                if role == Role.ETHERNET and self._quality_report.get("state") != "archived":
                    self._quality_unknown("Normal closure, inspection or archival was not confirmed; inspect preserved files.")
            self._repo.update_session(plan.session_id, phase, demo=False, inspections=inspections,
                                      monitoring=dict(self._monitor_reports),
                                      capture_quality=dict(self._quality_report),
                                      inspection=inspections.get(Role.ETHERNET.value),
                                      stop_results={role.value: {"success": result.success, "state": result.state,
                                                                "evidence": result.evidence, "details": result.details}
                                                    for role, result in results.items()})
        except Exception as error:
            self._storage_failed = True
            phase = SessionPhase.INCOMPLETE
            self._quality_unknown(error)
            log.exception("capture.finalization_failed")
            self._event("OPERATION_ERROR", level="ERROR", original=str(error))
            actual_paths = [str(file.final_path if file.final_path.is_file() else file.temp_path) for file in plan.files]
        try:
            cleanup_work_directory(plan.files[0].temp_path.parent)
        except OSError as error:
            log.exception("storage.work_directory_cleanup_failed")
            self._event("FILE_CLEANUP_WARNING", level="WARNING", original=str(error))
        self._set_phase(phase)
        self._publish("files", (actual_paths, "completed" if phase == SessionPhase.COMPLETED else
                                 "incomplete" if phase == SessionPhase.INCOMPLETE else "failed"))
        self._event("SESSION_" + phase.value.upper(), level="INFO" if phase == SessionPhase.COMPLETED else "WARNING",
                    demo=False, files_created=any(file.final_path.is_file() or file.temp_path.is_file()
                                                   for file in plan.files))
        self._refresh_file_history()
        return phase != SessionPhase.INCOMPLETE

    def diagnose(self, *, show: bool = True) -> Future:
        return self._submit(self._begin_diagnose, show)

    def _begin_diagnose(self, show: bool) -> None:
        if not self._closed:
            self._background(lambda: self._diagnose(False),
                             lambda future: self._finish_diagnose(future, show))

    def _finish_diagnose(self, future: Future, show: bool) -> None:
        if self._closed:
            return
        try:
            report = future.result()
            self._event("ENVIRONMENT_READY")
            if show:
                self._publish("environment", report)
        except Exception as error:
            log.exception("environment.check_failed")
            if show:
                self._publish("environment_error", str(error))
            self._event("OPERATION_ERROR", level="ERROR", original=str(error))

    def _diagnose(self, show: bool = True) -> dict:
        from vil_logging.diagnostics.environment import collect_environment
        report = collect_environment(tshark_path=self._settings.tshark_path if self._settings else "")
        log.info("environment.report", extra={"report": report})
        return report

    def request_exit(self) -> Future:
        with self._lock:
            self._exit_pending = True
            self._cancel.set()
        return self._submit(self._exit)

    def _exit(self) -> bool:
        if self.phase in {SessionPhase.RECORDING, SessionPhase.PARTIAL} or (
            self.phase == SessionPhase.INCOMPLETE and not self.demo and self._plan and not self._storage_failed
        ):
            self._stop()
        if self.phase in ACTIVE or self.phase == SessionPhase.INCOMPLETE:
            self._exit_pending = False
            self._event("SESSION_INCOMPLETE", level="WARNING", original="Exit postponed; unresolved state")
            self._publish("exit_ready", False)
            return False
        try:
            self._close_owned_resources()
        except Exception as error:
            log.exception("application.orderly_close_failed")
            self._exit_pending = False
            self._event("OPERATION_ERROR", level="ERROR", original=str(error))
            self._publish("exit_ready", False)
            return False
        self._publish("exit_ready", True)
        return True

    def _close_owned_resources(self, *, abnormal=False) -> None:
        if self._pool:
            if self.demo:
                self._pool.close()
            else:
                if abnormal and self._plan and self.phase in ACTIVE | {SessionPhase.INCOMPLETE}:
                    try:
                        self._repo.update_session(self._plan.session_id, SessionPhase.INCOMPLETE,
                                                  abnormal_owned_cleanup=True)
                    except Exception:
                        log.exception("capture.abnormal_state_save_failed")
                self._pool.close(abnormal=abnormal)
        if self._repo:
            self._repo.close()
        self._closed = True

    def close_for_test(self) -> None:
        """Final teardown after the event loop/test, never certify this as normal stop."""
        if not self._closed:
            self._executor.submit(self._close_owned_resources, abnormal=True).result(timeout=10)
        self._diagnostics.shutdown(wait=True, cancel_futures=True)
        self._executor.shutdown(wait=True, cancel_futures=True)
