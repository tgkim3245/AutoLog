"""Keep blocking multiprocessing transport out of the GUI event loop."""

import queue
import threading
from collections import OrderedDict, deque


class PacketBridge:
    def __init__(self, source, *, capacity=1000):
        self._source = source
        self._capacity = capacity
        self._packets = deque()
        self._drops = OrderedDict()
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._reader = threading.Thread(target=self._receive, name="AutoLog-display-IPC", daemon=True)
        self._reader.start()

    def _receive(self):
        while not self._closed.is_set():
            try:
                packet = self._source.get(timeout=.1)
            except queue.Empty:
                continue
            except (EOFError, OSError, ValueError):
                break
            if self._closed.is_set():
                break
            with self._lock:
                if len(self._packets) == self._capacity:
                    removed = self._packets.popleft()
                    session = removed.session_id
                    self._drops[session] = self._drops.get(session, 0) + 1
                    self._drops.move_to_end(session)
                    if len(self._drops) > 128:
                        self._drops.popitem(last=False)
                self._packets.append(packet)

    def drain(self, limit=100):
        with self._lock:
            return [self._packets.popleft() for _ in range(min(limit, len(self._packets)))]

    def dropped(self, session_id):
        with self._lock:
            return self._drops.get(session_id, 0)

    def close(self):
        # A partial IPC message can outlive the worker. Never join its reader
        # from shutdown or the GUI; this daemon owns no recorder/file handles.
        self._closed.set()
