"""The real worker shares command correlation, not simulator cleanup policy."""

import logging
import os
import time
from dataclasses import replace
from uuid import uuid4

from vil_logging.contracts.commands import Command
from vil_logging.contracts.models import Role
from vil_logging.workers.ethernet_worker import ethernet_worker_main
from vil_logging.workers.pool import FakeWorkerPool

log = logging.getLogger(__name__)


class EthernetWorkerPool(FakeWorkerPool):
    def __init__(self):
        super().__init__()
        self._jobs = {}

    def request(self, roles, action, session_id, **kwargs):
        results = super().request(roles, action, session_id, **kwargs)
        if os.name == "nt" and action in {"stop", "query"}:
            import win32job
            for role, result in list(results.items()):
                if not result.success or result.state != "stopped" or role not in self._jobs:
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
            raise ValueError("CANoe capture is not enabled in this stage")
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

    def close(self, *, abnormal=False):
        if self._closed:
            return
        if not abnormal and self._processes:
            for result in self.request(tuple(self._processes), "query", "shutdown-check", timeout=2).values():
                if not result.success or result.state in {"recording", "starting", "unknown"}:
                    raise RuntimeError("Real capture shutdown is unconfirmed; keep the application open")
        self._closed = True
        for role, pipe in self._pipes.items():
            try:
                pipe.send(Command("shutdown", role, "shutdown"))
            except (OSError, EOFError, BrokenPipeError):
                pass
        for role, process in self._processes.items():
            process.join(timeout=1)
            if process.is_alive() and abnormal:
                log.error("worker.abnormal_owned_job_cleanup", extra={"worker_pid": process.pid})
            if role in self._jobs:
                self._jobs.pop(role).Close()  # Active descendants only on abnormal app termination.
            if process.is_alive():
                process.join(timeout=1)
            if process.is_alive():
                process.terminate()  # Abnormal teardown, or idle worker after confirmed recorder exit.
                process.join(timeout=1)
            self._pipes[role].close()
            process.close()
        self._packets.cancel_join_thread()
        self._packets.close()
