"""Explicit simulation worker: never opens tools, NICs or capture files."""

import os
import queue
import time
import traceback
from multiprocessing.connection import Connection

from vil_logging.contracts.commands import Command, CommandResult, FakeBehavior
from vil_logging.contracts.models import PacketSummary, Role, utc_now


def worker_main(role: Role, pipe: Connection, packets, behavior: FakeBehavior) -> None:
    state = "idle"
    session_id = ""
    started = 0.0
    next_packet = 0.0
    packet_drops = 0
    command: Command | None = None
    try:
        while True:
            now = time.monotonic()
            if state == "recording" and behavior.fail_after is not None:
                if now - started >= behavior.fail_after:
                    state = "error"
            if role == Role.ETHERNET and state == "recording" and now >= next_packet:
                try:
                    packets.put_nowait(PacketSummary(
                        timestamp=utc_now(), source="192.0.2.10", destination="198.51.100.20",
                        protocol="UDP (demo)", length=64, source_mac="02:00:00:00:00:01",
                        destination_mac="02:00:00:00:00:02", session_id=session_id,
                    ))
                except queue.Full:
                    packet_drops += 1
                next_packet = now + 0.1
            if not pipe.poll(0.02):
                continue
            command = pipe.recv()
            if command.action == "shutdown":
                pipe.send(CommandResult(command, True, state, "demo worker shutdown", os.getpid()))
                break
            success = True
            evidence = "simulation only; no capture file created"
            if command.action == "prepare":
                state = "ready"
            elif command.action == "start":
                time.sleep(behavior.start_delay)
                if behavior.crash_on_start:
                    raise RuntimeError("injected demo worker exception")
                if behavior.fail_start:
                    success, state, evidence = False, "error", "injected demo start failure"
                elif state == "recording" and session_id != command.session_id:
                    success, evidence = False, "another demo session is recording"
                else:
                    state, session_id = "recording", command.session_id
                    started = time.monotonic()
            elif command.action == "stop":
                time.sleep(behavior.stop_delay)
                if session_id and command.session_id != session_id:
                    success, evidence = False, "session does not own this demo recording"
                elif behavior.fail_stop:
                    success, state, evidence = False, "unknown", "injected demo stop failure"
                else:
                    state = "stopped"
            elif command.action == "query":
                evidence = f"demo state={state}; observation_queue_drops={packet_drops}"
            else:
                success, evidence = False, f"unsupported internal command: {command.action}"
            pipe.send(CommandResult(command, success, state, evidence, os.getpid()))
    except (EOFError, BrokenPipeError, OSError):
        # Losing this pipe ends only a simulator. Real recorders require separate reconciliation.
        pass
    except Exception:
        if command is not None:
            try:
                pipe.send(CommandResult(command, False, "unknown", traceback.format_exc(), os.getpid()))
            except (EOFError, BrokenPipeError, OSError):
                pass
    finally:
        pipe.close()
