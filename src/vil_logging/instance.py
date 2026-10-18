"""Single UI process per Windows user session and application data directory."""

import ctypes
import hashlib
import os
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    activated = Signal()

    def __init__(self, data_dir: Path, *, name_prefix: str = "AutoLog"):
        super().__init__()
        data_dir.mkdir(parents=True, exist_ok=True)
        session_id = ctypes.c_ulong()
        if os.name == "nt":
            ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session_id))
        digest = hashlib.sha256(f"{data_dir.resolve()}:{session_id.value}".encode()).hexdigest()[:24]
        self.name = name_prefix + "_" + digest
        self.lock = QLockFile(str(data_dir / f"ui_{session_id.value}.lock"))
        self.lock.setStaleLockTime(0)
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._activate)
        self.owned = False

    def acquire(self, *, activate_existing: bool = True) -> bool:
        if not self.lock.tryLock(0):
            if not activate_existing:
                return False
            client = QLocalSocket()
            client.connectToServer(self.name)
            if not client.waitForConnected(1500):
                raise RuntimeError("Another instance holds the app lock but is not responding")
            client.write(b"show")
            client.waitForBytesWritten(300)
            client.disconnectFromServer()
            return False
        QLocalServer.removeServer(self.name)
        if not self.server.listen(self.name):
            self.lock.unlock()
            raise RuntimeError(self.server.errorString())
        self.owned = True
        return True

    def _activate(self) -> None:
        while self.server.hasPendingConnections():
            connection = self.server.nextPendingConnection()
            connection.disconnectFromServer()
            connection.deleteLater()
        self.activated.emit()

    def close(self) -> None:
        self.server.close()
        if self.owned:
            self.lock.unlock()
            self.owned = False
