"""One process per simulated target; commands are sent to all before any wait."""

import logging
import multiprocessing as mp
import threading
import time
from collections.abc import Mapping

from vil_logging.contracts.commands import Command, CommandResult, FakeBehavior, WorkerProgress
from vil_logging.contracts.models import PacketSummary, Role
from vil_logging.workers.fake_worker import worker_main
from vil_logging.workers.packet_bridge import PacketBridge

log = logging.getLogger(__name__)


class FakeWorkerPool:
    def __init__(self, behaviors: Mapping[Role, FakeBehavior] | None = None):
        self._context = mp.get_context("spawn")
        self._packets = self._context.Queue(maxsize=1000)
        self._display = PacketBridge(self._packets)
        self._pipes = {}
        self._processes = {}
        self._behaviors = dict(behaviors or {})
        self._closed = False

    def _ensure(self, role: Role) -> None:
        if role in self._processes:
            return
        parent, child = self._context.Pipe()
        process = self._context.Process(
            target=worker_main,
            args=(role, child, self._packets, self._behaviors.get(role, FakeBehavior())),
            name=f"VIL-demo-{role.value}", daemon=True,
        )
        process.start()
        child.close()
        self._pipes[role], self._processes[role] = parent, process
        log.info("worker.spawn", extra={"fields": {"role": role.value, "pid": process.pid}})

    @staticmethod
    def _log_progress(reply: WorkerProgress):
        log.info("command.progress", extra={"fields": {
            "command_id": reply.command.command_id, "session_id": reply.command.session_id,
            "role": reply.command.role.value, "action": reply.command.action, "worker_pid": reply.pid,
            **reply.fields,
        }})

    @staticmethod
    def _log_late_reply(reply: CommandResult, expected_command_id: str = "") -> None:
        log.warning("command.stale_reply", extra={"fields": {
            "command_id": reply.command.command_id, "expected_command_id": expected_command_id,
            "role": reply.command.role.value, "session_id": reply.command.session_id,
            "state": reply.state, "success": reply.success, "evidence": reply.evidence,
            "worker_pid": reply.pid,
        }})

    def _drain_late_replies(self, role: Role) -> None:
        pipe = self._pipes.get(role)
        if pipe is None:
            return
        for _ in range(16):
            try:
                if not pipe.poll():
                    break
                reply = pipe.recv()
                if isinstance(reply, WorkerProgress):
                    self._log_progress(reply)
                else:
                    self._log_late_reply(reply)
            except (EOFError, OSError, BrokenPipeError):
                break

    def request(
        self, roles: tuple[Role, ...], action: str, session_id: str, *,
        timeout: float = 3.0, cancel: threading.Event | None = None,
        params: dict | None = None,
        role_params: dict | None = None,
    ) -> dict[Role, CommandResult]:
        if self._closed:
            raise RuntimeError("worker pool is closed")
        pending = {}
        results = {}
        started = time.monotonic()
        for role in roles:
            values = (role_params or {}).get(role, params or {})
            command = Command(action=action, role=role, session_id=session_id, params=dict(values))
            try:
                self._ensure(role)
                if self._closed:
                    raise RuntimeError("worker pool is closed")
                self._drain_late_replies(role)
                self._pipes[role].send(command)
            except (OSError, EOFError, BrokenPipeError, RuntimeError) as error:
                self._drain_late_replies(role)
                results[role] = CommandResult(command, False, "unknown", str(error))
                log.exception("command.send_failed", extra={"fields": {
                    "role": role.value, "action": action, "command_id": command.command_id,
                    "session_id": session_id,
                }})
                continue
            pending[role] = command
            log.debug("command.sent", extra={"fields": {
                "command_id": command.command_id, "session_id": session_id,
                "generation": command.generation, "role": role.value, "action": action,
                "params": command.params,
            }})
        while pending and time.monotonic() - started < timeout:
            if cancel is not None and cancel.is_set():
                break
            for role, command in list(pending.items()):
                try:
                    if not self._pipes[role].poll():
                        if not self._processes[role].is_alive():
                            results[role] = CommandResult(command, False, "unknown", "worker exited")
                            del pending[role]
                        continue
                    reply: CommandResult = self._pipes[role].recv()
                except (EOFError, BrokenPipeError, OSError) as error:
                    results[role] = CommandResult(command, False, "unknown", str(error))
                    del pending[role]
                    continue
                if isinstance(reply, WorkerProgress):
                    self._log_progress(reply)
                    continue
                if reply.command != command:
                    self._log_late_reply(reply, command.command_id)
                    continue
                results[role] = reply
                del pending[role]
                log.info("command.result", extra={"fields": {
                    "command_id": command.command_id, "session_id": session_id,
                    "generation": command.generation, "role": role.value, "action": action,
                    "success": reply.success, "state": reply.state, "evidence": reply.evidence,
                    "worker_pid": reply.pid, "elapsed_ms": round((time.monotonic()-started)*1000, 2),
                    "details": reply.details,
                }})
            if pending:
                time.sleep(0.005)
        for role, command in pending.items():
            evidence = "start cancelled; stop and reconciliation required" if (
                cancel is not None and cancel.is_set()
            ) else "command timed out; actual state not confirmed"
            results[role] = CommandResult(command, False, "unknown", evidence)
            log.error("command.unconfirmed", extra={"fields": {
                "command_id": command.command_id, "session_id": session_id,
                "role": role.value, "action": action, "evidence": evidence,
            }})
        return results

    def drain_packets(self, limit: int = 100) -> list[PacketSummary]:
        if self._closed:
            return []
        return self._display.drain(limit)

    def force_abort(self):
        """Terminate only tracked worker handles; no joins or pipe/COM requests."""
        self._closed = True
        if display := getattr(self, "_display", None):
            display.close()
        for process in tuple(self._processes.values()):
            try:
                if process.is_alive():
                    process.terminate()
            except (OSError, ValueError, AssertionError):
                pass

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for role in self._pipes:
            try:
                self._pipes[role].send(Command("shutdown", role, "shutdown"))
            except (OSError, EOFError, BrokenPipeError):
                pass
        for role, process in self._processes.items():
            process.join(timeout=1.0)
            if process.is_alive():
                log.warning("worker.demo_terminate", extra={"fields": {"role": role.value}})
                process.terminate()  # Only these owned simulators; never a real recording tool.
                process.join(timeout=1.0)
            self._pipes[role].close()
            process.close()
        self._display.close()
        self._packets.cancel_join_thread()
        self._packets.close()
