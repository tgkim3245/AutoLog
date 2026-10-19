import sys
import threading
import time
from types import SimpleNamespace

from vil_logging.adapters.capture_observer import CaptureObserver


def test_observer_follows_append_and_finishes_after_recorder_closes(tmp_path):
    path = tmp_path / "growing.pcap"
    stopped = threading.Event()
    recorder = SimpleNamespace(poll=lambda: 0 if stopped.is_set() else None)
    code = "import sys; data=sys.stdin.buffer.read(); sys.stdout.buffer.write(data)"
    observer = CaptureObserver([sys.executable, "-c", code], path, recorder)
    path.write_bytes(b"header")
    time.sleep(.06)
    with path.open("ab") as stream:
        stream.write(b"last_packet")
    stopped.set()
    observer.finish()
    try:
        assert observer.process.stdout.read() == b"headerlast_packet"
        assert observer.bytes_fed == len(b"headerlast_packet")
        assert not observer.errors
    finally:
        observer.process.stdout.close()


def test_stalled_decoder_is_disposable_without_touching_capture(tmp_path):
    path = tmp_path / "raw.pcap"
    payload = b"x" * (1024 * 1024)
    path.write_bytes(payload)
    recorder = SimpleNamespace(poll=lambda: 0)
    observer = CaptureObserver([sys.executable, "-c", "import time; time.sleep(60)"], path, recorder)
    observer.finish(timeout=.1)
    observer.process.stdout.close()
    assert not observer.feeder.is_alive()
    assert path.read_bytes() == payload
    assert any("timed out" in error for error in observer.errors)
