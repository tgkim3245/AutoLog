"""Bounded, asynchronous developer diagnostics.

The application keeps this service enabled for its lifetime. Callers should log
operational metadata, never capture contents. Bytes and commonly named payload
fields are redacted as an additional safeguard; this is not a general text
anonymizer.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import queue
import struct
import sys
import threading
import time
import traceback
import zipfile
from datetime import datetime, timezone
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4


class DebugLogError(RuntimeError):
    """Developer diagnostics could not be queued, written, or closed."""


_RECORD_KEYS = frozenset(logging.makeLogRecord({}).__dict__) | {
    "message", "asctime", "debug_event", "debug_fields", "debug_exception",
    "debug_monotonic_ns", "fields",
}
_PAYLOAD_KEYS = frozenset({
    "raw", "data", "payload", "packet", "frame", "rawdata", "rawbytes",
    "packetdata", "packetbytes", "framedata", "framebytes", "vehicledata",
    "vehiclepayload", "packetpayload", "capturebytes", "payloadbytes",
})


def _safe_value(value: Any, *, key: str = "", depth: int = 0) -> Any:
    normalized = "".join(character for character in key.casefold() if character.isalnum())
    if normalized in _PAYLOAD_KEYS:
        return "<redacted capture content>"
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<redacted bytes: {len(value)}>"
    if depth > 8:
        return "<maximum diagnostic depth>"
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, str):
        return value if len(value) <= 8192 else value[:8192] + "<truncated>"
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        result = {
            str(item_key): _safe_value(item, key=str(item_key), depth=depth + 1)
            for item_key, item in list(value.items())[:100]
        }
        if len(value) > 100:
            result["_truncated_fields"] = len(value) - 100
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        result = [_safe_value(item, depth=depth + 1) for item in list(value)[:100]]
        if len(value) > 100:
            result.append(f"<{len(value) - 100} more items>")
        return result
    # Avoid an unknown object's repr exposing its internal data or credentials.
    return f"<{type(value).__name__}>"


def _exception_details(error: BaseException) -> dict[str, str]:
    return {
        "type": type(error).__name__,
        "message": str(error)[:8192],
        "traceback": "".join(traceback.format_exception(type(error), error, error.__traceback__))[:32768],
    }


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        document: dict[str, Any] = {
            "timestamp_utc": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "monotonic_ns": record.debug_monotonic_ns,
            "level": record.levelname,
            "logger": record.name,
            "pid": record.process,
            "process_name": record.processName,
            "tid": record.thread,
            "thread_name": record.threadName,
            "event": record.debug_event,
            "fields": record.debug_fields,
        }
        if record.debug_exception is not None:
            document["exception"] = record.debug_exception
        return json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class _StrictRotatingHandler(RotatingFileHandler):
    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802 - logging API
        error = sys.exc_info()[1]
        if error is not None:
            raise error
        raise DebugLogError("Developer log write failed without an exception")


class _DiagnosticQueueHandler(QueueHandler):
    def __init__(self, records: queue.Queue, failure: Callable[[BaseException, str], None]) -> None:
        super().__init__(records)
        self._failure = failure
        self._accepting = True

    def deactivate(self) -> None:
        # Wait for an in-progress producer before enqueueing the stop sentinel.
        with self.lock:
            self._accepting = False

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        prepared = copy.copy(record)
        prepared.debug_monotonic_ns = time.monotonic_ns()
        prepared.debug_event = str(getattr(record, "debug_event", record.getMessage()))[:8192]
        supplied_fields = getattr(record, "fields", {})
        extras = dict(supplied_fields) if isinstance(supplied_fields, dict) else {"fields": supplied_fields}
        extras.update({key: value for key, value in record.__dict__.items() if key not in _RECORD_KEYS})
        extras.update(getattr(record, "debug_fields", {}))
        prepared.debug_fields = _safe_value(extras)
        prepared.debug_exception = getattr(record, "debug_exception", None)
        if prepared.debug_exception is None and record.exc_info and record.exc_info[1]:
            prepared.debug_exception = _exception_details(record.exc_info[1])
        prepared.exc_info = None
        prepared.exc_text = None
        prepared.args = None
        prepared.msg = prepared.debug_event
        return prepared

    def enqueue(self, record: logging.LogRecord) -> None:
        # Diagnostics must not stall acquisition; record queue overflow in health.
        self.queue.put_nowait(record)

    def emit(self, record: logging.LogRecord) -> None:
        if not self._accepting:
            return
        try:
            self.enqueue(self.prepare(record))
        except Exception as error:
            event = getattr(record, "debug_event", record.msg)
            self._failure(error, event if isinstance(event, str) else "<unformattable event>")


class _DiagnosticListener(QueueListener):
    def __init__(self, records: queue.Queue, handler: logging.Handler, failure: Callable[[BaseException, str], None]) -> None:
        super().__init__(records, handler, respect_handler_level=True)
        self._failure = failure
        self._write_error: BaseException | None = None

    def handle(self, record: logging.LogRecord) -> None:
        flush_event = getattr(record, "_debug_flush_event", None)
        if flush_event is not None:
            try:
                for handler in self.handlers:
                    handler.flush()
            except Exception as error:
                self._write_error = error
                self._failure(error, "developer_log.flush")
            finally:
                flush_event.set()
            return
        if self._write_error is not None:
            self._failure(self._write_error, record.debug_event)
            return
        try:
            super().handle(record)
        except Exception as error:
            self._write_error = error
            self._failure(error, record.debug_event)

    def enqueue_sentinel(self) -> None:
        # QueueListener's default put_nowait can fail during a busy shutdown.
        self.queue.put(self._sentinel)

    def flush_pending(self, timeout: float = 10.0) -> None:
        """Wait until all records already queued have reached the file handler."""
        flushed = threading.Event()
        record = logging.LogRecord(__name__, logging.DEBUG, __file__, 0, "", (), None)
        record._debug_flush_event = flushed
        self.queue.put(record, timeout=timeout)
        if not flushed.wait(timeout):
            raise TimeoutError("Timed out while flushing the developer log")


class DebugLogService:
    """Collect ``vil_logging.*`` records into a bounded rolling log.

    ``log`` enqueues records without interrupting acquisition on diagnostic
    failures. ``disable``/``close`` drain and close the file and surface failures.
    UI integrations must inspect ``last_error`` or call ``check_health`` during
    normal status refresh, so a write failure is explicitly shown to the user.
    The fixed filename preserves the configured size bound across launches.
    """

    def __init__(self, data_dir: Path, *, max_bytes: int = 5 * 1024 * 1024,
                 backup_count: int = 4, log_dir: Path | None = None) -> None:
        if max_bytes < 1 or backup_count < 1:
            raise ValueError("max_bytes and backup_count must both be positive")
        self._data_dir = Path(data_dir)
        self._log_dir = Path(log_dir) if log_dir is not None else self._data_dir / "developer_logs"
        self._max_bytes = max_bytes
        self._backup_count = backup_count
        self._lock = threading.RLock()
        self._failure_lock = threading.Lock()
        self._last_error: BaseException | None = None
        self._failed_record_count = 0
        self._queue_overflow_count = 0
        self._last_failed_event: str | None = None
        self._enabled = False
        self._closed = False
        self._path: Path | None = None
        self._handler: _DiagnosticQueueHandler | None = None
        self._file_handler: _StrictRotatingHandler | None = None
        self._listener: _DiagnosticListener | None = None
        self._package_logger = logging.getLogger("vil_logging")
        self._previous_level: int | None = None

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    @property
    def log_path(self) -> Path | None:
        """Current or most recently closed file; None until first activation."""
        with self._lock:
            return self._path

    @property
    def last_error(self) -> BaseException | None:
        with self._failure_lock:
            return self._last_error

    @property
    def failed_record_count(self) -> int:
        with self._failure_lock:
            return self._failed_record_count

    @property
    def queue_overflow_count(self) -> int:
        with self._failure_lock:
            return self._queue_overflow_count

    @property
    def last_failed_event(self) -> str | None:
        with self._failure_lock:
            return self._last_failed_event

    def _record_failure(self, error: BaseException, event: str | None = None) -> None:
        with self._failure_lock:
            if self._last_error is None:
                self._last_error = error
            if event is not None:
                self._failed_record_count += 1
                self._last_failed_event = event[:8192]
                if isinstance(error, queue.Full):
                    self._queue_overflow_count += 1

    def check_health(self) -> None:
        error = self.last_error
        if error is not None:
            if isinstance(error, queue.Full):
                raise DebugLogError(
                    f"Developer log queue overflowed; {self.queue_overflow_count} records could not be saved"
                ) from error
            raise DebugLogError("Developer log storage failed; check the output disk or permissions") from error

    def enable(self) -> Path:
        with self._lock:
            if self._closed:
                raise RuntimeError("Developer log service has been closed")
            if self._enabled:
                self.check_health()
                assert self._path is not None
                return self._path
            with self._failure_lock:
                self._last_error = None
                self._failed_record_count = 0
                self._queue_overflow_count = 0
                self._last_failed_event = None
            directory = self._log_dir
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / "AutoLog_developer.jsonl"
            output = _StrictRotatingHandler(
                path, maxBytes=self._max_bytes, backupCount=self._backup_count,
                encoding="utf-8", errors="strict",
            )
            output.setFormatter(_JsonFormatter())
            output.setLevel(logging.DEBUG)
            records: queue.Queue = queue.Queue(maxsize=4096)
            handler = _DiagnosticQueueHandler(records, self._record_failure)
            handler.setLevel(logging.DEBUG)
            listener = _DiagnosticListener(records, output, self._record_failure)
            try:
                listener.start()
            except BaseException:
                output.close()
                handler.close()
                raise
            self._file_handler = output
            self._handler = handler
            self._listener = listener
            self._path = path
            self._previous_level = self._package_logger.level
            self._package_logger.setLevel(logging.DEBUG)
            self._package_logger.addHandler(handler)
            self._enabled = True
            from vil_logging import __version__

            bits = struct.calcsize("P") * 8
            platform_description = f"{sys.platform} ({bits}-bit process)"
            if sys.platform == "win32":
                version = sys.getwindowsversion()
                platform_description = f"Windows {version.major}.{version.minor}.{version.build} ({bits}-bit process)"
            self.log(
                "developer_log.enabled", app_version=__version__,
                python_version=".".join(map(str, sys.version_info[:3])), python_executable=sys.executable,
                platform=platform_description, process_bits=bits, schema_version=1,
                max_bytes=self._max_bytes, backup_count=self._backup_count,
                privacy="Operational metadata only; capture bytes and payload fields are redacted",
            )
            return path

    def export_report(self, destination_dir: Path) -> Path:
        """Export the current rolling log and its backups as one ZIP archive."""
        destination_dir = Path(destination_dir)
        with self._lock:
            if self._closed or not self._enabled:
                raise RuntimeError("Developer log is not active")
            path = self._path
            output = self._file_handler
            listener = self._listener
            assert path is not None and output is not None and listener is not None
            destination_dir.mkdir(parents=True, exist_ok=True)
            listener.flush_pending()

            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            report = destination_dir / f"AutoLog_BugReport_To_Taegon.Kim_{stamp}_{uuid4().hex[:8]}.zip"
            temporary = report.with_name(f".{report.name}.{uuid4().hex[:8]}.tmp")
            # The listener has drained all records up to the barrier. Holding the
            # rotating handler lock keeps filenames stable while the archive is
            # assembled; newer records remain queued and are written afterward.
            output.acquire()
            try:
                log_files = [path.with_name(f"{path.name}.{index}")
                             for index in range(self._backup_count, 0, -1)] + [path]
                log_files = [item for item in log_files if item.is_file()]
                if not log_files:
                    raise FileNotFoundError("No developer log files are available to export")
                manifest = {"created_utc": datetime.now(timezone.utc).isoformat(), "send_to": "Taegon.Kim",
                            "snapshot": "Developer logs at export time; source logs continue growing.", "files": []}
                with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    for log_file in log_files:
                        digest, size = hashlib.sha256(), 0
                        with log_file.open("rb") as source, archive.open(log_file.name, "w") as destination:
                            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                                destination.write(chunk)
                                digest.update(chunk)
                                size += len(chunk)
                        manifest["files"].append({"name": log_file.name, "bytes": size, "sha256": digest.hexdigest()})
                    archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
                with zipfile.ZipFile(temporary) as archive:
                    if archive.testzip() is not None:
                        raise DebugLogError("Bug report ZIP integrity check failed")
                    for item in manifest["files"]:
                        digest, size = hashlib.sha256(), 0
                        with archive.open(item["name"]) as source:
                            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                                digest.update(chunk)
                                size += len(chunk)
                        if (size, digest.hexdigest()) != (item["bytes"], item["sha256"]):
                            raise DebugLogError("Bug report snapshot content verification failed")
                temporary.replace(report)
            finally:
                output.release()
                temporary.unlink(missing_ok=True)
            return report

    def log(self, event: str, level: str = "INFO", **fields: Any) -> None:
        numeric_level = logging.getLevelNamesMapping().get(level.upper())
        if numeric_level is None:
            raise ValueError(f"Unknown log level: {level}")
        with self._lock:
            if not self._enabled:
                return
            self._package_logger.log(numeric_level, event, extra={"debug_event": event, "debug_fields": fields})

    def exception(self, event: str, error: BaseException, **fields: Any) -> None:
        with self._lock:
            if not self._enabled:
                return
            self._package_logger.error(event, extra={
                "debug_event": event, "debug_fields": fields,
                "debug_exception": _exception_details(error),
            })

    def disable(self) -> None:
        with self._lock:
            if not self._enabled:
                self.check_health()
                return
            # Record the transition even if another package logger has a filter.
            handler, listener, output = self._handler, self._listener, self._file_handler
            assert handler is not None and listener is not None and output is not None
            try:
                error = self.last_error
                record = self._package_logger.makeRecord(
                    "vil_logging", logging.INFO, __file__, 0,
                    "developer_log.disabled", (), None,
                    extra={"debug_event": "developer_log.disabled", "debug_fields": {
                        "failed_record_count": self.failed_record_count,
                        "queue_overflow_count": self.queue_overflow_count,
                        "last_failed_event": self.last_failed_event,
                        "last_error_type": type(error).__name__ if error else None,
                        "last_error_message": str(error) if error else None,
                    }},
                )
                handler.handle(record)
            except Exception as error:
                self._record_failure(error)
            finally:
                handler.deactivate()
                self._package_logger.removeHandler(handler)
                self._enabled = False
                if self._package_logger.level == logging.DEBUG and self._previous_level is not None:
                    self._package_logger.setLevel(self._previous_level)
                try:
                    listener.stop()
                except Exception as error:
                    self._record_failure(error)
                try:
                    output.flush()
                except Exception as error:
                    self._record_failure(error)
                finally:
                    try:
                        output.close()
                    except Exception as error:
                        self._record_failure(error)
                    handler.close()
                    self._handler = None
                    self._listener = None
                    self._file_handler = None
            self.check_health()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                self.check_health()
                return
            try:
                self.disable()
            finally:
                self._closed = True
