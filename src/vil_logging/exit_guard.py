"""Bound app exit independently of the GUI, coordinator and vendor COM calls."""

import os
import threading


class ExitGuard:
    def __init__(self, abort, *, timeout=1.0, abort_timeout=.25, terminate=os._exit):
        self.abort = abort
        self.timeout = timeout
        self.abort_timeout = abort_timeout
        self.terminate = terminate
        self._lock = threading.Lock()
        self._requested = False
        self._forcing = False
        self._finished = False
        self._terminated = False
        self._timer = None

    def request(self):
        with self._lock:
            if self._finished:
                return
            repeated = self._requested
            self._requested = True
            if not repeated:
                self._timer = threading.Timer(self.timeout, self.force, args=("deadline",))
                self._timer.daemon = True
                self._timer.start()
        if repeated:
            self.force("repeat_close")

    def force(self, reason="cleanup_failed"):
        with self._lock:
            if self._forcing or self._finished:
                return
            self._forcing = True
        threading.Thread(target=self._abort, args=(reason,), daemon=True, name="One Click Log-force-exit").start()

    def _terminate(self):
        with self._lock:
            if self._terminated:
                return
            self._terminated = True
        self.terminate(0)

    def _abort(self, reason):
        # Even cleanup/debug I/O cannot postpone the final process exit.
        deadline = threading.Timer(self.abort_timeout, self._terminate)
        deadline.daemon = True
        deadline.start()
        try:
            self.abort(reason)
        finally:
            self._terminate()
            deadline.cancel()

    def finish(self):
        with self._lock:
            self._finished = True
            if self._timer is not None:
                self._timer.cancel()
