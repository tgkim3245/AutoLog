"""One CANoe COM apartment per target; no CANoe process is force-terminated."""

import os
import time
import traceback

from vil_logging.adapters.canoe import CanoeCapture
from vil_logging.adapters.external import configure_worker_environment
from vil_logging.contracts.commands import CommandResult, WorkerProgress


def canoe_worker_main(role, pipe):
    import pythoncom

    configure_worker_environment()
    pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
    capture = CanoeCapture()
    try:
        while True:
            if not pipe.poll(.05):
                pythoncom.PumpWaitingMessages()
                continue
            command = pipe.recv()
            trace_started = time.monotonic()
            capture.emit_trace = lambda fields: pipe.send(WorkerProgress(command, fields, os.getpid()))
            try:
                if command.action in {"connect", "prepare"}:
                    details = getattr(capture, command.action)(command.params)
                    state, evidence = "ready", "Exact owned CANoe configuration and existing Logging Block inspected"
                elif command.action in {"configure", "start"}:
                    details = getattr(capture, command.action)(command.session_id, command.params)
                    state = "configured" if command.action == "configure" else "recording"
                    evidence = "Exact BLF path confirmed" if state == "configured" else "Trigger active and BLF header at exact path"
                elif command.action == "stop":
                    details = capture.stop(command.session_id)
                    state, evidence = "stopped", "Selected trigger inactive; BLF completeness checked separately; measurement untouched"
                elif command.action == "restore":
                    details = capture.restore_output(command.session_id)
                    state, evidence = "stopped", "Idle output settings restored without saving the configuration"
                elif command.action == "inspect":
                    details = capture.inspect_file(command.session_id)
                    state, evidence = "verified", "BLF container integrity, record boundaries and counts checked"
                elif command.action == "query":
                    state, details = capture.query()
                    evidence = details.get("error", "Owned configuration, measurement and logging trigger observed")
                elif command.action == "shutdown":
                    if capture.attempted and not capture.stop_confirmed:
                        raise RuntimeError("Cannot release CANoe while this segment's normal stop is unconfirmed")
                    capture.restore_output(capture.session_id)
                    pipe.send(CommandResult(command, True, "stopped", "COM reference released; CANoe window/measurement remain", os.getpid()))
                    break
                else:
                    raise ValueError("Unsupported CANoe command")
                pipe.send(CommandResult(command, True, state, evidence, os.getpid(), details=details))
            except Exception as error:
                capture.record_failure(command.action, error)
                details = capture.stats()
                issue = getattr(error, "connection_issue", "")
                if issue:
                    details["connection_issue"] = issue
                    details["settings_path"] = getattr(error, "settings_path", "")
                    details["running_canoe_pids"] = getattr(error, "process_ids", [])
                elif any(item.get("event") == "canoe.instance_reused"
                         and item.get("monotonic", 0) >= trace_started for item in details.get("diagnostics", [])):
                    details["connection_issue"] = "restart_required"
                pipe.send(CommandResult(command, False, "unknown", traceback.format_exc(), os.getpid(),
                                        details=details))
    except (EOFError, OSError, BrokenPipeError):
        pass  # Abnormal loss is not a normal stop; preserve the real CANoe process.
    finally:
        capture.block = capture.app = None
        pipe.close()
        pythoncom.CoUninitialize()
