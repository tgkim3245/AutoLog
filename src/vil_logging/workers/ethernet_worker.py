"""Real Ethernet commands in a dedicated, parent-owned process/job."""

import os
import traceback

from vil_logging.adapters.external import configure_worker_environment
from vil_logging.adapters.tshark import TSharkCapture
from vil_logging.contracts.commands import CommandResult


def ethernet_worker_main(role, pipe, packets):
    configure_worker_environment()
    capture = TSharkCapture(packets)
    try:
        while True:
            command = pipe.recv()
            try:
                if command.action == "prepare":
                    details = capture.prepare(command.params)
                    state, evidence = "ready", "TShark version, exact NIC and inspection tool verified; no capture opened"
                elif command.action == "start":
                    details = capture.start(command.session_id, command.params)
                    state, evidence = "recording", "Capture notice + valid file/interface header + sustained owned process"
                elif command.action == "stop":
                    details = capture.stop(command.session_id)
                    state, evidence = "stopped", "Owned capture exited; stdout/stderr reached EOF"
                elif command.action == "inspect":
                    details = capture.inspect_file(command.session_id)
                    state, evidence = "verified", "Closed capture fully read by capinfos; actual format checked"
                elif command.action == "query":
                    state, details = capture.query()
                    evidence = "Owned TShark process state and summary counters"
                elif command.action == "shutdown":
                    state, details = capture.query()
                    if state in {"recording", "starting"}:
                        raise RuntimeError("Refusing to exit a worker with an active capture")
                    pipe.send(CommandResult(command, True, "stopped", "Worker shutdown", os.getpid(), details=details))
                    break
                else:
                    raise ValueError("Unsupported Ethernet command")
                pipe.send(CommandResult(command, True, state, evidence, os.getpid(), details=details))
            except Exception:
                pipe.send(CommandResult(command, False, "unknown", traceback.format_exc(), os.getpid(),
                                        details=capture.stats()))
    except (EOFError, OSError, BrokenPipeError):
        # The parent's job owns this worker and its TShark/dumpcap descendants.
        # Pipe loss is abnormal; it must never become normal capture completion.
        pass
    finally:
        packets.cancel_join_thread()  # UI summary backlog must not hold an exited recorder's worker open.
        pipe.close()
