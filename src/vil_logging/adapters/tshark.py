"""Dumpcap owns raw recording; TShark decodes a growing file independently."""

import csv
import io
import queue
import struct
import subprocess
import threading
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

from vil_logging.adapters.capture_observer import CaptureObserver
from vil_logging.adapters.external import external_environment, launch_capture, request_normal_stop
from vil_logging.contracts.models import PacketSummary
from vil_logging.diagnostics.capture_quality import CaptureMetrics, validate_buffer
from vil_logging.diagnostics.connections import (
    _find_tshark,
    _nic_key,
    _parse_tshark_interfaces,
    _run_query,
)
from vil_logging.diagnostics.environment import _version_response
from vil_logging.diagnostics.network_activity import capture_link_state
from vil_logging.monitors.engine import MonitorEngine
from vil_logging.monitors.rules import address, parse_rules
from vil_logging.storage.pcapng_stats import capture_loss_report

FIELDS = ("frame.time_epoch", "eth.src", "eth.dst", "ip.src", "ipv6.src", "ip.dst", "ipv6.dst",
          "_ws.col.Protocol", "frame.len")
_PCAP_MAGIC = {b"\xd4\xc3\xb2\xa1", b"\xa1\xb2\xc3\xd4", b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d"}


def capture_header_ready(path: Path, file_format: str) -> bool:
    try:
        with path.open("rb") as source:
            header = source.read(8192)
    except OSError:
        return False
    if file_format == "pcap":
        return len(header) >= 24 and header[:4] in _PCAP_MAGIC
    if len(header) < 28 or header[:4] != b"\x0a\x0d\x0d\x0a":
        return False
    order = "<" if header[8:12] == b"\x4d\x3c\x2b\x1a" else ">"
    position = 0
    while position + 12 <= len(header):
        kind, length = struct.unpack_from(order + "II", header, position)
        if length < 12 or length % 4 or position + length > len(header):
            return False
        if struct.unpack_from(order + "I", header, position + length - 4)[0] != length:
            return False
        if kind == 1:  # Interface Description Block, also present in a zero-packet file.
            return True
        position += length
    return False


def parse_summary(line: str, session_id: str) -> PacketSummary:
    values = line.rstrip("\r\n").split("\t")
    if len(values) != len(FIELDS):
        raise ValueError("Unexpected TShark summary field count")
    epoch, source_mac, destination_mac, ipv4_src, ipv6_src, ipv4_dst, ipv6_dst, protocol, length = values
    count = int(length)
    if count < 0 or count > 2**31 - 1:
        raise ValueError("Invalid captured frame length")
    timestamp = datetime.fromtimestamp(float(epoch), UTC).isoformat(timespec="milliseconds")
    source_ip, destination_ip = address(ipv4_src or ipv6_src), address(ipv4_dst or ipv6_dst)
    return PacketSummary(timestamp, source_ip or source_mac,
                         destination_ip or destination_mac, protocol, count,
                         source_mac, destination_mac, session_id, source_ip, destination_ip, float(epoch))


class TSharkCapture:
    def __init__(self, packets):
        self.packets = packets
        self.process: subprocess.Popen | None = None
        self._observer = None
        self.session_id = ""
        self.binding: dict = {}
        self.path: Path | None = None
        self._threads: list[threading.Thread] = []
        self._stderr = deque(maxlen=80)
        self._notice = threading.Event()
        self._stats_lock = threading.Lock()
        self._parsed = self._dropped = self._parse_errors = 0
        self._read_errors = []
        self._stop_requested = False
        self._started = False
        self._last_packet = None
        self._monitor = MonitorEngine()
        self._monitor_error = ""
        self._stdout_eof = False
        self._metrics = CaptureMetrics()
        self._last_delay = self._max_delay = None
        self._emit_summaries = True

    def prepare(self, params: dict) -> dict:
        if self.process and self.process.poll() is None:
            raise RuntimeError("A capture is already active")
        tool = _find_tshark(str(params.get("tshark_path", "")))
        if tool["status"] != "ready":
            raise RuntimeError(tool["message_ko"] + "\n" + tool.get("detail", ""))
        nic_id = str(params.get("nic_id", ""))
        if not nic_id:
            raise ValueError("캡처할 네트워크를 먼저 선택하세요.")
        listing = _run_query([tool["path"], "-D"], timeout=3)
        if not listing["success"]:
            raise RuntimeError(listing.get("detail") or listing.get("stderr") or "NIC query failed")
        selected = next((item for item in _parse_tshark_interfaces(listing.get("stdout", ""))
                         if _nic_key(item["id"]) == _nic_key(nic_id)), None)
        if not selected:
            raise ValueError("선택한 네트워크를 캡처 도구에서 찾지 못했습니다. 다시 선택하세요.")
        file_format = params.get("file_format", "pcap")
        if file_format not in {"pcap", "pcapng"}:
            raise ValueError("Unsupported capture format")
        buffer_mib = validate_buffer(params.get("buffer_mib", "64"))
        capinfos = Path(tool["path"]).with_name("capinfos.exe")
        dumpcap = Path(tool["path"]).with_name("dumpcap.exe")
        dumpcap_version = _version_response(dumpcap)
        if dumpcap_version["status"] != "present" or "Dumpcap" not in dumpcap_version.get("stdout", ""):
            raise ValueError("dumpcap.exe is required for independent raw capture. Check your Wireshark installation.")
        version = _version_response(capinfos)
        if version["status"] != "present" or "Capinfos" not in version.get("stdout", ""):
            raise ValueError("파일 검사 도구 capinfos.exe가 필요합니다. Wireshark 설치를 확인하세요.")
        self.binding = {"tshark_path": tool["path"], "nic_id": selected["id"],
                        "nic_name": selected["name"], "file_format": file_format,
                        "requested_buffer_mib": buffer_mib,
                        "capinfos_path": str(capinfos), "dumpcap_path": str(dumpcap),
                        "capture_engine": "dumpcap", "decoder": "tshark_growing_file", "tool_version": tool["version"]}
        return self.binding.copy()

    def start(self, session_id: str, params: dict, timeout: float = 15) -> dict:
        if not self.binding:
            raise RuntimeError("Prepare the capture binding first")
        if self.process and self.process.poll() is None:
            raise RuntimeError("A capture is already active")
        for thread in self._threads:
            thread.join(timeout=2)
        if any(thread.is_alive() for thread in self._threads):
            raise RuntimeError("Previous capture readers have not finished; a new session is blocked")
        if self.process:
            for stream in (self.process.stdout, self.process.stderr):
                if stream and not stream.closed:
                    stream.close()
        if self._observer:
            self._observer.process.stdout.close()
            self._observer = None
        path = Path(params["temp_path"])
        if path.exists() or path.is_symlink() or not path.parent.is_dir():
            raise ValueError("The private capture path is not empty or its folder is unavailable")
        if path.suffix != "." + self.binding["file_format"]:
            raise ValueError("Capture format and filename disagree")
        self.session_id, self.path = session_id, path
        self._emit_summaries = params.get("emit_summaries", True)
        self._stderr.clear()
        self._notice.clear()
        self._parsed = self._dropped = self._parse_errors = 0
        self._read_errors = []
        self._last_packet = None
        self._stdout_eof = False
        self._metrics = CaptureMetrics()
        self._last_delay = self._max_delay = None
        self._monitor_error = ""
        try:
            self._monitor = MonitorEngine(parse_rules(params.get("monitor_rules_json", "")), session_id)
        except Exception as error:
            self._monitor = MonitorEngine(session_id=session_id)
            self._monitor_error = str(error)
        self._stop_requested = self._started = False
        arguments = [self.binding["dumpcap_path"], "-q", "-i", self.binding["nic_id"],
                     "-B", str(self.binding.get("requested_buffer_mib", 64)),
                     "-w", str(path), "-F", self.binding["file_format"]]
        decoder = [self.binding["tshark_path"], "-n", "-l", "-r", "-", "-T", "fields",
                     "-E", "separator=/t", "-E", "occurrence=f", "-E", "escape=y"]
        for field in FIELDS:
            decoder.extend(("-e", field))
        # Used only by explicit localhost verification; normal capture has no
        # display or capture filter and saves all traffic on the selected NIC.
        if params.get("verification_filter"):
            if self.binding["nic_id"] != r"\Device\NPF_Loopback":
                raise ValueError("Verification filters are restricted to the loopback interface")
            arguments.extend(("-f", params["verification_filter"]))
        self.process = launch_capture(arguments)
        try:
            self._observer = CaptureObserver(decoder, path, self.process)
        except OSError as error:
            self._read_errors.append("Decoder unavailable: " + str(error))
        self._threads = [threading.Thread(target=self._consume_stdout, daemon=True, name="capture-fields"),
                         threading.Thread(target=self._consume_stderr, daemon=True, name="capture-errors")]
        for thread in self._threads:
            thread.start()
        deadline = time.monotonic() + timeout
        header_since = None
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("Dumpcap exited during start: " + self.evidence())
            ready = self._notice.is_set() and capture_header_ready(path, self.binding["file_format"])
            header_since = (header_since or time.monotonic()) if ready else None
            if header_since and time.monotonic() - header_since >= .15:
                with self._stats_lock:
                    self._started = True
                    self._monitor_call("activate")
                return self.stats()
            time.sleep(.02)
        raise TimeoutError("Dumpcap capture readiness was not confirmed: " + self.evidence())

    def _consume_stdout(self):
        try:
            if not self._observer:
                return
            stream = self._observer.process.stdout
            discard = False
            while chunk := stream.readline(16_384):
                complete = chunk.endswith(b"\n")
                if discard or not complete:
                    if not discard:
                        with self._stats_lock:
                            self._parse_errors += 1
                            self._monitor_call("invalidate", "parse_error")
                    discard = not complete
                    continue
                try:
                    packet = parse_summary(chunk.decode("utf-8", errors="strict"), self.session_id)
                except (ValueError, OverflowError, OSError, UnicodeError):
                    with self._stats_lock:
                        self._parse_errors += 1
                        self._monitor_call("invalidate", "parse_error")
                    continue
                with self._stats_lock:
                    self._parsed += 1
                    self._last_packet = packet.timestamp
                    delay = (time.time() - packet.captured_epoch) * 1000
                    self._last_delay = round(delay, 3) if delay >= 0 else None
                    if self._last_delay is not None:
                        self._max_delay = max(self._max_delay or 0, self._last_delay)
                    self._monitor_call("feed", packet)
                if self._emit_summaries:
                    try:
                        self.packets.put_nowait(packet)
                    except queue.Full:
                        with self._stats_lock:
                            self._dropped += 1
        except (OSError, ValueError) as error:
            with self._stats_lock:
                self._read_errors.append(str(error))
        finally:
            with self._stats_lock:
                self._stdout_eof = True

    def _consume_stderr(self):
        try:
            while chunk := self.process.stderr.readline(4096):
                text = chunk.decode("utf-8", errors="replace").strip()
                with self._stats_lock:
                    self._stderr.append(text)
                if text.startswith("Capturing on "):
                    self._notice.set()
        except (OSError, ValueError) as error:
            with self._stats_lock:
                self._read_errors.append(str(error))

    def evidence(self) -> str:
        with self._stats_lock:
            return "\n".join(self._stderr)[-8192:]

    def _monitor_call(self, method, *args, **kwargs):
        if not self._monitor_error:
            try:
                return getattr(self._monitor, method)(*args, **kwargs)
            except Exception as error:
                import traceback
                self._monitor_error = traceback.format_exc()[-8192:] or str(error)
        return {"session_id": self.session_id, "status": "unknown", "rules": [],
                "reasons": ["monitor_internal_error"], "error": self._monitor_error}

    def stats(self) -> dict:
        with self._stats_lock:
            stats = {"parsed_packets": self._parsed, "summary_drops": self._dropped,
                     "parse_errors": self._parse_errors, "reader_errors": list(self._read_errors),
                     "last_packet_utc": self._last_packet, "started": self._started,
                     "monitor": self._monitor_call("snapshot", reader_ok=not self._stdout_eof and not self._read_errors
                                                   and not (self._observer and self._observer.errors))}
            last_delay, max_delay = self._last_delay, self._max_delay
        # Filesystem I/O stays outside the receive lock: slow storage must not
        # stop stdout draining just to update a status panel.
        try:
            stats["performance"] = self._metrics.sample(self.path, stats["parsed_packets"],
                                                        last_delay=last_delay, max_delay=max_delay)
        except Exception as error:
            stats["performance"] = {"error": str(error), "sampled_epoch": time.time()}
        stats.update(capture_pid=self.process.pid if self.process else None,
                     exit_code=self.process.poll() if self.process else None,
                     temp_path=str(self.path) if self.path else "", session_id=self.session_id,
                     binding=self.binding.copy(), stderr=self.evidence())
        if self._observer:
            stats["decoder"] = {"pid": self._observer.process.pid,
                                "exit_code": self._observer.process.poll(),
                                "bytes_fed": self._observer.bytes_fed,
                                "errors": list(self._observer.errors)}
            stats["reader_errors"].extend(self._observer.errors)
        return stats

    def query(self) -> tuple[str, dict]:
        if not self.process:
            return "ready" if self.binding else "idle", self.stats()
        if self.process.poll() is None:
            details = self.stats()
            details["link"] = capture_link_state(self.binding["nic_id"])
            return "recording" if self._started else "starting", details
        return "stopped" if self._stop_requested else "error", self.stats()

    def stop(self, session_id: str, timeout: float = 30) -> dict:
        if self.session_id and session_id != self.session_id:
            if self.process and self.process.poll() is None:
                raise ValueError("This session does not own the capture")
            return {**self.stats(), "not_started_for_session": True}
        self._stop_requested = True
        if self.process:
            request_normal_stop(self.process)
            self.process.wait(timeout=timeout)
            if self._observer:
                self._observer.finish()
            for thread in self._threads:
                thread.join(timeout=2)
            if any(thread.is_alive() for thread in self._threads):
                raise TimeoutError("Capture output pipes did not reach EOF")
            self.process.stdout.close()
            self.process.stderr.close()
            if self._observer:
                self._observer.process.stdout.close()
        with self._stats_lock:
            self._monitor_call("stop")
        self._metrics.finish()
        return self.stats()

    def inspect_file(self, session_id: str, timeout: float = 60) -> dict:
        deadline = time.monotonic() + timeout
        if session_id != self.session_id or self.process is None or self.process.poll() is None:
            raise ValueError("Capture closure is not confirmed for this session")
        if not self._stop_requested or self.process.returncode != 0:
            raise ValueError("Capture did not exit normally; preserve the working file")
        if self.path.is_symlink() or not capture_header_ready(self.path, self.binding["file_format"]):
            raise ValueError("Capture header is missing or does not match its selected format")
        before = self.path.stat()
        result = subprocess.run([self.binding["capinfos_path"], "-T", "-B", "-Q", "-r", "-t", "-c", str(self.path)],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=timeout, env=external_environment(),
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise ValueError("Capture file could not be read completely: " + result.stderr[-8192:])
        rows = list(csv.reader(io.StringIO(result.stdout), delimiter="\t"))
        if len(rows) != 1 or len(rows[0]) != 3:
            raise ValueError("Unrecognized capinfos result")
        file_type, packet_count = rows[0][1], int(rows[0][2])
        allowed = {"pcap", "nsecpcap"} if self.binding["file_format"] == "pcap" else {"pcapng"}
        if file_type not in allowed or packet_count < 0:
            raise ValueError("Recorded file type does not match the selected format")
        loss = capture_loss_report(self.path, self.binding["file_format"],
                                   timeout=max(.01, min(15, deadline - time.monotonic())))
        after = self.path.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise ValueError("Capture file changed during inspection")
        statistics = self.stats()
        consistency = {"file_packets": packet_count, "parsed_packets": statistics["parsed_packets"],
                       "same_count": packet_count == statistics["parsed_packets"],
                       "unparsed_file_packets": max(0, packet_count - statistics["parsed_packets"]),
                       "scope": "count_comparison_only"}
        return {"actual_format": file_type, "packet_count": packet_count, "bytes": after.st_size,
                "mtime_ns": after.st_mtime_ns, "inode": after.st_ino,
                "capture_loss": loss, "summary_consistency": consistency,
                "validation": "capinfos_full_read", "warning": result.stderr[-4096:], **statistics}
