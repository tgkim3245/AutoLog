"""Bounded capture telemetry; filesystem sampling never holds the receive lock."""

import shutil
import time
from pathlib import Path

LOW_SPACE_BYTES = 1024 ** 3
SPACE_RECOVERY_BYTES = LOW_SPACE_BYTES * 5 // 4


def validate_buffer(value):
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal() or len(value) > 4:
        raise ValueError("캡처 버퍼는 1~1024 MiB 정수여야 합니다. / Capture buffer must be 1–1024 MiB.")
    if not 1 <= int(value) <= 1024:
        raise ValueError("Capture buffer must be 1–1024 MiB")
    return int(value)


class CaptureMetrics:
    def __init__(self, *, monotonic=time.monotonic):
        self.clock = monotonic
        self.started = self.previous_time = self.clock()
        self.ended = None
        self.previous_count = self.previous_bytes = 0
        self.parsed_pps = self.file_bps = None
        self._finished_sample = None

    def finish(self):
        if self.ended is None:
            self.ended = self.clock()

    def sample(self, path: Path | None, parsed_packets: int, *, last_delay=None, max_delay=None):
        if self._finished_sample and self._finished_sample["path"] == str(path or ""):
            return dict(self._finished_sample)
        now = self.clock()
        size = free = None
        errors = []
        if path is not None:
            try:
                size = path.stat().st_size
            except OSError as error:
                errors.append(str(error))
            try:
                free = shutil.disk_usage(path.parent).free
            except OSError as error:
                errors.append(str(error))
        elapsed = (self.ended if self.ended is not None else now) - self.started
        interval = now - self.previous_time
        if self.ended is None and interval >= .2:
            self.parsed_pps = max(0, parsed_packets - self.previous_count) / interval
            self.file_bps = (max(0, size - self.previous_bytes) / interval if size is not None else None)
            self.previous_time, self.previous_count = now, parsed_packets
            if size is not None:
                self.previous_bytes = size
        result = {"sampled_epoch": time.time(), "elapsed_seconds": max(0, elapsed), "file_bytes": size,
                "file_growth_bps": self.file_bps, "parsed_pps": self.parsed_pps,
                "last_processing_delay_ms": last_delay, "max_processing_delay_ms": max_delay,
                "disk_free_bytes": free, "low_space": free is not None and free <= LOW_SPACE_BYTES,
                "error": "\n".join(errors), "path": str(path or ""), "finished": self.ended is not None}
        if self.ended is not None:
            self._finished_sample = dict(result)
        return result
