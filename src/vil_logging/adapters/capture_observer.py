"""Feed a growing capture to a read-only decoder; backpressure stays off the recorder."""

import subprocess
import threading
from collections import deque

from vil_logging.adapters.external import external_environment


class CaptureObserver:
    def __init__(self, arguments, path, recorder):
        self.path, self.recorder = path, recorder
        self.errors = deque(maxlen=20)
        self.bytes_fed = 0
        self.cancelled = threading.Event()
        self.process = subprocess.Popen(arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, bufsize=0, env=external_environment(),
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.feeder = threading.Thread(target=self._follow, daemon=True, name="capture-file-follower")
        self.reader = threading.Thread(target=self._stderr, daemon=True, name="decoder-errors")
        self.feeder.start()
        self.reader.start()

    def _follow(self):
        try:
            while not self.path.exists():
                if self.recorder.poll() is not None or self.cancelled.wait(.02):
                    return
            with self.path.open("rb", buffering=0) as source:
                while not self.cancelled.is_set():
                    chunk = source.read(64 * 1024)
                    if chunk:
                        remaining = memoryview(chunk)
                        while remaining and not self.cancelled.is_set():
                            written = self.process.stdin.write(remaining)
                            if not written:
                                raise BrokenPipeError("Decoder stopped accepting capture bytes")
                            self.bytes_fed += written
                            remaining = remaining[written:]
                    elif self.recorder.poll() is not None:
                        # Re-read after confirming closure so final buffered bytes are not skipped.
                        chunk = source.read(64 * 1024)
                        if chunk:
                            source.seek(-len(chunk), 1)
                            continue
                        break
                    else:
                        self.cancelled.wait(.02)
        except (OSError, ValueError) as error:
            self.errors.append(str(error))
        finally:
            try:
                self.process.stdin.close()
            except (OSError, ValueError):
                pass

    def _stderr(self):
        try:
            while line := self.process.stderr.readline(4096):
                self.errors.append(line.decode("utf-8", errors="replace").strip())
        except (OSError, ValueError) as error:
            self.errors.append(str(error))

    def finish(self, timeout=5):
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.errors.append("Decoder drain timed out; original capture remains complete")
            self.cancelled.set()
            # This process reads stdin only: it owns no NIC or output capture file.
            self.process.kill()
            self.process.wait(timeout=3)
        self.cancelled.set()
        self.feeder.join(timeout=3)
        self.reader.join(timeout=3)
        if self.feeder.is_alive() or self.reader.is_alive():
            raise TimeoutError("Decoder readers are still releasing the capture file")
        if self.process.returncode:
            self.errors.append(f"Decoder exited with code {self.process.returncode}")
        self.process.stderr.close()
