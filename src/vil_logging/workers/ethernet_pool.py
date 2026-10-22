"""Real CANoe/TShark workers share correlation, with separate ownership rules."""

import logging
import os
import time
from dataclasses import replace
from uuid import uuid4

from vil_logging.contracts.models import Role
from vil_logging.workers.canoe_worker import canoe_worker_main
from vil_logging.workers.ethernet_worker import ethernet_worker_main
from vil_logging.workers.owned_canoe import OwnedCanoe
from vil_logging.workers.pool import FakeWorkerPool

log = logging.getLogger(__name__)


class CaptureWorkerPool(FakeWorkerPool):
    def __init__(self):
        super().__init__()
        self._jobs = {}
        self._owned_canoe = OwnedCanoe()
        self._resources_closed = False

    def _log_progress(self, reply):
        FakeWorkerPool._log_progress(reply)
        if reply.fields.get("event") == "canoe.independent_instance_created":
            self._owned_canoe.remember(reply.fields["canoe_pid"])

    def request(self, roles, action, session_id, **kwargs):
        results = super().request(roles, action, session_id, **kwargs)
        if display := getattr(self, "_display", None):
            for role, result in list(results.items()):
                if role == Role.ETHERNET and result.details.get("session_id"):
                    dropped = display.dropped(result.details["session_id"])
                    results[role] = replace(result, details={**result.details,
                        "display_transport_drops": dropped,
                        "summary_drops": result.details.get("summary_drops", 0) + dropped})
        if os.name == "nt" and action in {"stop", "query"}:
            import win32job
            for role, result in list(results.items()):
                if not result.success or result.state not in {"idle", "ready", "stopped"} or role not in self._jobs:
                    continue
                deadline = time.monotonic() + 2
                while True:
                    accounting = win32job.QueryInformationJobObject(
                        self._jobs[role], win32job.JobObjectBasicAccountingInformation)
                    active = accounting["ActiveProcesses"]
                    if active <= 1 or time.monotonic() >= deadline:
                        break
                    time.sleep(.02)
                details = {**result.details, "active_owned_processes": active}
                if active > 1:
                    results[role] = replace(result, success=False, state="unknown", details=details,
                                            evidence="Owned recorder descendants have not all exited")
                else:
                    results[role] = replace(result, details=details)
        return results

    def _ensure(self, role):
        if role != Role.ETHERNET:
            if role not in {Role.CAN, Role.DIAG}:
                raise ValueError("Unsupported capture role")
            if role not in self._processes:
                parent, child = self._context.Pipe()
                process = self._context.Process(target=canoe_worker_main, args=(role, child),
                                                name=f"AutoLog-CANoe-{role.value}", daemon=True)
                process.start()
                child.close()
                # CANoe is a user-visible COM server, never part of the kill-on-close capture job.
                self._pipes[role], self._processes[role] = parent, process
                log.info("worker.canoe_spawn", extra={"role": role.value, "worker_pid": process.pid})
            return
        if role in self._processes:
            return
        parent, child = self._context.Pipe()
        process = self._context.Process(target=ethernet_worker_main, args=(role, child, self._packets),
                                        name="VIL-ethernet", daemon=True)
        process.start()
        child.close()
        try:
            if os.name == "nt":
                import win32api
                import win32con
                import win32job
                job = win32job.CreateJobObject(None, f"AutoLog-{os.getpid()}-{uuid4().hex}")
                self._jobs[role] = job
                limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
                limits["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
                handle = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, process.pid)
                try:
                    win32job.AssignProcessToJobObject(job, handle)
                finally:
                    handle.Close()
            # No command is sent until the entire descendant tree is owned.
            self._pipes[role], self._processes[role] = parent, process
            log.info("worker.real_spawn", extra={"role": role.value, "worker_pid": process.pid,
                                                "windows_job": role in self._jobs})
        except Exception:
            process.terminate()  # No capture command has been sent at this point.
            process.join(timeout=2)
            process.close()
            parent.close()
            if role in self._jobs:
                self._jobs.pop(role).Close()
            raise

    def force_abort(self):
        # The job owns dumpcap/decoder descendants, even if their parent is hung.
        # Dedicated CANoe windows are tracked separately by verified process handles.
        if os.name == "nt":
            import win32job
            for job in tuple(self._jobs.values()):
                try:
                    win32job.TerminateJobObject(job, 1)
                except Exception:
                    pass
        super().force_abort()
        if owned := getattr(self, "_owned_canoe", None):
            owned.terminate()

    def close(self, *, abnormal=False):
        if getattr(self, "_resources_closed", False):
            return
        # X ends this run and its dedicated CANoe windows without waiting for COM.
        self.force_abort()
        for role, process in self._processes.items():
            process.join(timeout=.2)
            if role in self._jobs:
                self._jobs.pop(role).Close()  # Active descendants only on abnormal app termination.
            if process.is_alive():
                process.kill()
                process.join(timeout=.2)
            self._pipes[role].close()
            if not process.is_alive():
                process.close()
        self._display.close()
        self._packets.cancel_join_thread()
        self._packets.close()
        self._resources_closed = True
        log.info("worker.owned_resources_closed")


EthernetWorkerPool = CaptureWorkerPool  # Compatibility for previous verification scripts.
