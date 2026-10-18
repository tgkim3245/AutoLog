"""Control one newly-created CANoe instance and one existing logging block.

Never attach through the active-object table, save a configuration, create a
logging block, or start/stop measurement. COM stays in the worker's STA thread.
"""

import time
from collections import deque
from pathlib import Path

from vil_logging.storage.blf import inspect_blf
from vil_logging.storage.file_access import ExclusiveFile, observe


def _same_path(first, second):
    return str(Path(first).resolve()).casefold() == str(Path(second).resolve()).casefold()


def _create_application():
    from win32com.client import DispatchEx

    return DispatchEx("CANoe.Application")


def _identity(obj):
    if hasattr(obj, "_oleobj_"):
        import pythoncom
        return obj._oleobj_.QueryInterface(pythoncom.IID_IUnknown)
    return obj  # Test doubles, with the same identity checks as the real objects.


class CanoeCapture:
    def __init__(self, *, create_application=None):
        self._create_application = create_application or _create_application
        self.app = self.block = None
        self.cfg = ""
        self.index = 0
        self.session_id = ""
        self.path = None
        self.attempted = False
        self.stop_confirmed = False
        self.version = ""
        self.journal = deque(maxlen=40)
        self.emit_trace = None

    def _trace(self, event, **fields):
        entry = {"event": event, "monotonic": time.monotonic(), **fields}
        self.journal.append(entry)
        if self.emit_trace is not None:
            self.emit_trace(entry)

    def stats(self):
        return {"cfg": self.cfg, "logging_block": self.index, "session_id": self.session_id,
                "canoe_version": self.version,
                "path": str(self.path or ""), "start_attempted": self.attempted,
                "stop_confirmed": self.stop_confirmed, "diagnostics": list(self.journal)}

    def _validate(self):
        if self.app is None or not _same_path(self.app.Configuration.FullName, self.cfg):
            raise RuntimeError("CANoe configuration changed or window closed. Reconnect while measurement is stopped.")
        if self.block is not None:
            current = self.app.Configuration.OnlineSetup.LoggingCollection.Item(self.index)
            if _identity(current) != _identity(self.block):
                raise RuntimeError("Logging block changed. Reconnect and select the intended block again.")

    def _require_single_file(self):
        options = self.block.FileNameOptions
        if any(bool(getattr(options, name)) for name in (
                "IncrementAfterTrigger", "IncrementAfterGrowth", "IncrementAfterDuration")):
            raise RuntimeError("Automatic log splitting/incrementation changed; disable it before starting.")

    def connect(self, params):
        cfg = Path(str(params.get("cfg_path", ""))).resolve()
        if cfg.suffix.lower() != ".cfg" or not cfg.is_file():
            raise ValueError("Choose an existing CANoe .cfg file first.")
        if self.attempted and not self.stop_confirmed:
            raise RuntimeError("Resolve the previous recording before reconnecting.")
        if self.app is not None:
            try:
                current_cfg = self.app.Configuration.FullName
            except Exception as error:
                self._trace("canoe.idle_reference_lost", error=str(error))
                self.app = self.block = None
                current_cfg = ""
        if self.app is not None:
            if not _same_path(self.cfg, cfg) or not _same_path(current_cfg, self.cfg):
                if self.app.Measurement.Running:
                    raise RuntimeError("Stop measurement manually before changing the configuration.")
                self.app = self.block = None  # Leave the old CANoe window and edits with its user.
            else:
                # Explicit Connect may select a new block after an idle manual edit.
                self.block, self.index = None, 0
        if self.app is None:
            self._trace("canoe.create_requested", cfg=str(cfg))
            app = self._create_application()
            # DispatchEx must give a fresh application. Never replace any existing project.
            if str(app.Configuration.FullName).strip() or app.Measurement.Running:
                raise RuntimeError("CANoe returned an existing configuration; refusing to replace it.")
            app.Visible = True
            self.app, self.cfg = app, str(cfg)
            self.block, self.index = None, 0
            self.app.Open(str(cfg), False, True)  # No automatic save; let CANoe show its own prompts.
            self._validate()
            try:
                self.version = str(self.app.Version.FullName)
            except Exception:
                self.version = "unknown"
            self._trace("canoe.configuration_opened", cfg=self.cfg)
        self._validate()
        collection = self.app.Configuration.OnlineSetup.LoggingCollection
        count = int(collection.Count)
        if not 0 < count <= 128:
            raise RuntimeError("No existing Logging Block was found, or the block count is unsupported.")
        blocks = [{"id": str(i), "name": str(collection.Item(i).FullName)} for i in range(1, count + 1)]
        selected = str(params.get("logging_block", ""))
        if not selected and count == 1:
            selected = "1"
        index = int(selected) if selected.isdecimal() else 0
        if not 0 <= index <= count:
            raise ValueError("The remembered Logging Block no longer exists. Select it again.")
        self.index = index
        self.block = collection.Item(index) if index else None
        self.session_id, self.path = "", None
        self.attempted = self.stop_confirmed = False
        details = {**self.stats(), "blocks": blocks, "selected_block": str(index) if index else "",
                   "measurement_running": bool(self.app.Measurement.Running),
                   "trigger_active": bool(self.block.Trigger.Active) if self.block is not None else None,
                   "automatic_splitting": [name for name in (
                       "IncrementAfterTrigger", "IncrementAfterGrowth", "IncrementAfterDuration")
                       if self.block is not None and bool(getattr(self.block.FileNameOptions, name))]}
        self._trace("canoe.connected", block=index, measurement_running=details["measurement_running"])
        return details

    def prepare(self, params):
        details = self.connect(params)
        if self.block is None:
            raise RuntimeError("Select the intended Logging Block in settings, then check the connection again.")
        self._validate()
        if not self.app.Measurement.Running:
            raise RuntimeError("Start measurement in the AutoLog-created CANoe window, then check again. AutoLog does not start measurement.")
        if self.block.Trigger.Active:
            raise RuntimeError("The selected Logging Block is already recording. Stop it manually before AutoLog starts a new segment.")
        splitting = details["automatic_splitting"]
        if splitting:
            raise RuntimeError("Disable automatic log splitting/incrementation in this Logging Block: " + ", ".join(splitting))
        self._trace("canoe.prepared", block=self.index)
        return {**details, **self.stats()}

    def configure(self, session_id, params):
        self._validate()
        if self.block is None or not self.app.Measurement.Running or self.block.Trigger.Active:
            raise RuntimeError("Measurement must be running and the selected logging trigger must be idle.")
        self._require_single_file()
        path = Path(params["temp_path"]).resolve()
        if path.suffix.lower() != ".blf" or path.exists() or not path.parent.is_dir():
            raise ValueError("A new BLF working path is required; existing files are preserved.")
        self._trace("canoe.output_apply_requested", previous=str(self.block.FullName), requested=str(path))
        self.block.FullName = str(path)
        self._validate()
        if not _same_path(self.block.FullName, path) or not self.app.Measurement.Running:
            raise RuntimeError("CANoe did not accept the exact output path while keeping measurement running.")
        self.session_id, self.path = session_id, path
        self.attempted = self.stop_confirmed = False
        self._trace("canoe.output_confirmed", path=str(path))
        return self.stats()

    def start(self, session_id, params):
        self._validate()
        if self.session_id != session_id or self.path is None or not _same_path(params["temp_path"], self.path):
            raise RuntimeError("BLF output must be configured and confirmed before reserving/starting.")
        if self.path.exists() or self.attempted or not self.app.Measurement.Running or self.block.Trigger.Active:
            raise RuntimeError("A fresh working path, running measurement and idle trigger are required.")
        self._require_single_file()
        if not _same_path(self.block.FullName, self.path):
            raise RuntimeError("Output filename changed after preparation; start is blocked.")
        self.attempted = True  # Record intent before a COM call can time out or raise.
        self.stop_confirmed = False
        self._trace("canoe.trigger_start_requested")
        self.block.Trigger.Start()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            self._validate()
            if not self.app.Measurement.Running:
                raise RuntimeError("Measurement stopped during segment start.")
            if self.block.Trigger.Active and self.path.is_file():
                try:
                    with self.path.open("rb") as source:
                        valid = source.read(4) == b"LOGG"
                except OSError:
                    valid = False  # Initial file sharing/flush may settle after the trigger acknowledgement.
                if valid:
                    self._trace("canoe.segment_started", trigger_active=True, path=str(self.path))
                    return self.stats()
            time.sleep(.05)
        raise TimeoutError("CANoe segment start is unconfirmed: need an active trigger and BLF header at the exact path.")

    def query(self):
        if self.app is None or not self.attempted or self.stop_confirmed:
            return "stopped", self.stats()
        self._validate()
        running = bool(self.app.Measurement.Running)
        active = bool(self.block.Trigger.Active)
        if active and running and self.path.is_file() and _same_path(self.block.FullName, self.path):
            return "recording", {**self.stats(), "measurement_running": running, "trigger_active": active}
        return "error", {**self.stats(), "measurement_running": running, "trigger_active": active,
                         "error": "Measurement, logging trigger or exact output no longer matches this session"}

    def stop(self, session_id):
        if not self.attempted:
            return self.stats()  # No Start was issued; never stop someone else's trigger.
        if session_id != self.session_id:
            raise RuntimeError("Stop belongs to a different CANoe recording session.")
        if self.stop_confirmed:
            return self.stats()
        self._validate()
        if not _same_path(self.block.FullName, self.path):
            raise RuntimeError("Logging output changed externally; refusing to stop another segment.")
        self._trace("canoe.trigger_stop_requested")
        if self.block.Trigger.Active:
            self.block.Trigger.Stop()
        deadline = time.monotonic() + 28
        last_error = ""
        while time.monotonic() < deadline:
            self._validate()
            if not self.block.Trigger.Active:
                try:
                    with ExclusiveFile(self.path, observe(self.path)):
                        pass
                except (OSError, ValueError) as error:
                    last_error = str(error)
                else:
                    self.stop_confirmed = True
                    self._trace("canoe.segment_closed", measurement_running=bool(self.app.Measurement.Running))
                    return self.stats()
            time.sleep(.05)
        raise TimeoutError("CANoe normal stop / exclusive file close is unconfirmed: " + last_error)

    def inspect_file(self, session_id):
        if session_id != self.session_id or not self.stop_confirmed:
            raise RuntimeError("Inspect only this session's normally stopped, closed BLF.")
        with ExclusiveFile(self.path, observe(self.path)):
            pass
        result = inspect_blf(self.path)
        return {**result, **self.stats()}
