"""Capture thread stacks once per GUI stall, without recording packet contents."""

import logging
import sys
import threading
import time
import traceback

log = logging.getLogger(__name__)


class UiResponsiveness:
    def __init__(self, *, threshold=5.0, start=True):
        self._threshold = threshold
        self._pulse = time.monotonic()
        self._reported = False
        self._closed = threading.Event()
        if start:
            threading.Thread(target=self._watch, name="AutoLog-UI-watch", daemon=True).start()

    def pulse(self):
        self._pulse = time.monotonic()

    def check(self):
        lag = time.monotonic() - self._pulse
        if lag >= self._threshold and not self._reported:
            self._reported = True
            names = {thread.ident: thread.name for thread in threading.enumerate()}
            stacks = [{"thread": names.get(identifier, str(identifier)),
                       "stack": "".join(traceback.format_stack(frame, limit=24))}
                      for identifier, frame in list(sys._current_frames().items())[:32]]
            log.warning("ui.unresponsive", extra={"fields": {"seconds": round(lag, 3), "threads": stacks}})
        elif lag < self._threshold and self._reported:
            self._reported = False
            log.info("ui.responsive_again")

    def _watch(self):
        while not self._closed.wait(1):
            self.check()

    def close(self):
        self._closed.set()
