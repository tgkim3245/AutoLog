"""Control one newly-created CANoe instance and one existing logging block.

Never attach through the active-object table, save a configuration, create a
logging block, or start/stop measurement. COM stays in the worker's STA thread.
"""

import time
from collections import deque
from pathlib import Path

from vil_logging.storage.blf import inspect_blf
from vil_logging.storage.file_access import ExclusiveFile, observe

FILE_OPTIONS = ("IncrementAtMeasurementStart", "IncrementAfterTrigger",
                "IncrementAfterGrowth", "IncrementAfterDuration")


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
        self._output_snapshot = None
        self.output_restore_error = ""

    def _trace(self, event, **fields):
        entry = {"event": event, "monotonic": time.monotonic(), **fields}
        self.journal.append(entry)
        if self.emit_trace is not None:
            self.emit_trace(entry)

    def stats(self):
        return {"cfg": self.cfg, "logging_block": self.index, "session_id": self.session_id,
                "canoe_version": self.version,
                "path": str(self.path or ""), "start_attempted": self.attempted,
                "stop_confirmed": self.stop_confirmed,
                "output_restore_pending": self._output_snapshot is not None,
                "output_restore_error": self.output_restore_error, "diagnostics": list(self.journal)}

    def _validate(self):
        if self.app is None or not _same_path(self.app.Configuration.FullName, self.cfg):
            raise RuntimeError("CANoe configuration changed or window closed. Reconnect while measurement is stopped.")
        if self.block is not None:
            current = self.app.Configuration.OnlineSetup.LoggingCollection.Item(self.index)
            if _identity(current) != _identity(self.block):
                raise RuntimeError("Logging block changed. Reconnect and select the intended block again.")

    def _require_single_file(self):
        options = self.block.FileNameOptions
        if any(bool(getattr(options, name)) for name in FILE_OPTIONS):
            raise RuntimeError("Logging filename options changed after preparation; start is blocked.")

    def restore_output(self, session_id):
        """Undo only our idle output changes; keep the snapshot when external edits conflict."""
        snapshot = self._output_snapshot
        if snapshot is None:
            return self.stats()
        if session_id != self.session_id:
            raise RuntimeError("Output restoration belongs to a different recording session.")
        try:
            if self.attempted and not self.stop_confirmed:
                raise RuntimeError("Normal segment stop must be confirmed before restoring output settings.")
            self._validate()
            if self.block.Trigger.Active:
                raise RuntimeError("Logging trigger became active; output settings were preserved.")
            current_path = str(self.block.FullName)
            if not (_same_path(current_path, self.path) or current_path == snapshot["full_name"]):
                raise RuntimeError("Logging output was edited externally; restoration would overwrite it.")
            options = self.block.FileNameOptions
            # Validate every property before any write. Original values also allow a retry
            # after a COM setter applied a value but failed to acknowledge the call.
            for name, original in snapshot["options"].items():
                if bool(getattr(options, name)) not in (False, original):
                    raise RuntimeError(f"{name} was edited externally; restoration was deferred.")
            self._trace("canoe.output_restore_requested", original=snapshot)
            if current_path != snapshot["full_name"]:
                self.block.FullName = snapshot["full_name"]
            for name, original in snapshot["options"].items():
                if bool(getattr(options, name)) != original:
                    setattr(options, name, original)
            if str(self.block.FullName) != snapshot["full_name"] or any(
                    bool(getattr(options, name)) != value for name, value in snapshot["options"].items()):
                raise RuntimeError("CANoe did not confirm restored output settings.")
        except Exception as error:
            self.output_restore_error = str(error)
            self._trace("canoe.output_restore_failed", error=str(error))
            raise
        self._output_snapshot = None
        self.output_restore_error = ""
        self._trace("canoe.output_restored")
        return self.stats()

    def _fresh_state(self, app):
        # Local-server activation can return before the CANoe model is ready.
        # Retry only COM failures; a successfully observed existing project is never opened over.
        deadline = time.monotonic() + 20
        while True:
            try:
                configuration = app.Configuration
                return str(configuration.FullName), bool(app.Measurement.Running), bool(configuration.Modified)
            except Exception as error:
                if not hasattr(error, "hresult") or time.monotonic() >= deadline:
                    raise
                info = getattr(error, "excepinfo", None)
                # Vector's single-client server has no Configuration object until
                # Open. An E_FAIL here is expected only for this verified mode.
                # All successfully read existing projects still take the refusal path.
                if (error.hresult & 0xFFFFFFFF == 0x80020009 and info and isinstance(info[5], int) and
                        info[5] & 0xFFFFFFFF == 0x80004005):
                    from vil_logging.diagnostics.canoe_setup import (
                        registered_settings_file,
                        single_client_enabled,
                    )
                    settings_file = registered_settings_file(str(app.FullName))
                    if single_client_enabled(settings_file) and not app.Measurement.Running:
                        self._trace("canoe.unconfigured_single_client", settings_file=str(settings_file))
                        return "", False, False
                import pythoncom
                pythoncom.PumpWaitingMessages()
                time.sleep(.1)

    def connect(self, params):
        cfg = Path(str(params.get("cfg_path", ""))).resolve()
        if cfg.suffix.lower() != ".cfg" or not cfg.is_file():
            raise ValueError("Choose an existing CANoe .cfg file first.")
        if self.attempted and not self.stop_confirmed:
            raise RuntimeError("Resolve the previous recording before reconnecting.")
        if self._output_snapshot is not None:
            self.restore_output(self.session_id)
        if self.app is not None:
            try:
                current_cfg = self.app.Configuration.FullName
            except Exception as error:
                self._trace("canoe.idle_reference_lost", error=str(error))
                self.app = self.block = None
                current_cfg = ""
        if self.app is not None:
            if not _same_path(current_cfg, self.cfg) and not _same_path(current_cfg, cfg):
                raise RuntimeError("The owned CANoe window changed to another configuration. "
                                   "Select that exact configuration or close the unused window and reconnect.")
            if not _same_path(current_cfg, cfg):
                if self.app.Measurement.Running:
                    raise RuntimeError("Stop measurement manually before changing the configuration.")
                if self.app.Configuration.Modified:
                    raise RuntimeError("The CANoe configuration has unsaved edits. Resolve them in CANoe "
                                       "before switching configurations; AutoLog does not save or discard them.")
                self._trace("canoe.configuration_switch_requested", previous=self.cfg, requested=str(cfg))
                self.app.Open(str(cfg), False, True)
            # Explicit Connect may adopt the user's exact chosen project in the owned
            # window, or select a new block, without dropping/recreating its COM handle.
            self.cfg = str(cfg)
            self.block, self.index = None, 0
        if self.app is None:
            self._trace("canoe.create_requested", cfg=str(cfg))
            app = self._create_application()
            # DispatchEx must give a fresh application. Never replace any existing project.
            current, running, modified = self._fresh_state(app)
            if current.strip() or running or modified:
                self._trace("canoe.instance_reused", requested=str(cfg), current=current, modified=modified)
                raise RuntimeError(
                    "CANoe returned an existing configuration; refusing to replace it. "
                    "Independent COM activation is unavailable. Close only unused CANoe windows and reconnect. "
                    "For CAN + Diag, verify Vector's SingleCOMClient setting and license on the test PC; "
                    "AutoLog does not change the global can.ini. "
                    f"Requested: {cfg}; returned: {current}")
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
        blocks = []
        for i in range(1, count + 1):
            item = collection.Item(i)
            output = str(item.FullName)
            blocks.append({"id": str(i), "name": str(item.Name), "path": output,
                           "format": Path(output).suffix.lower().lstrip("."),
                           "compatible": Path(output).suffix.lower() == ".blf"})
        selected = str(params.get("logging_block", ""))
        compatible = [item["id"] for item in blocks if item["compatible"]]
        if not selected and len(compatible) == 1:
            selected = compatible[0]
        index = int(selected) if selected.isdecimal() else 0
        if not 0 <= index <= count:
            index = 0
        selection_error = ""
        if selected and not index:
            selection_error = "The remembered Logging Block no longer exists. Select it again."
        elif index and not blocks[index - 1]["compatible"]:
            selection_error = "Select a BLF Logging Block. This block uses another format."
            index = 0
        self.index = index
        self.block = collection.Item(index) if index else None
        self.session_id, self.path = "", None
        self.attempted = self.stop_confirmed = False
        details = {**self.stats(), "blocks": blocks, "selected_block": str(index) if index else "",
                   "measurement_running": bool(self.app.Measurement.Running),
                   "view_only": "view only" in self.version.casefold(),
                   "selection_error": selection_error,
                   "trigger_active": bool(self.block.Trigger.Active) if self.block is not None else None,
                   "automatic_splitting": [name for name in FILE_OPTIONS
                       if self.block is not None and bool(getattr(self.block.FileNameOptions, name))]}
        self._trace("canoe.connected", block=index, measurement_running=details["measurement_running"])
        return details

    def prepare(self, params):
        details = self.connect(params)
        if self.block is None:
            raise RuntimeError(details["selection_error"] or
                               "Select the intended BLF Logging Block in settings, then check the connection again.")
        self._validate()
        if details["view_only"]:
            raise RuntimeError("CANoe is in View Only mode. Activate a measurement license on the test PC first.")
        if not self.app.Measurement.Running:
            raise RuntimeError("Start measurement in the AutoLog-created CANoe window, then check again. AutoLog does not start measurement.")
        if self.block.Trigger.Active:
            raise RuntimeError("The selected Logging Block is already recording. Stop it manually before AutoLog starts a new segment.")
        self._trace("canoe.prepared", block=self.index)
        return {**details, **self.stats()}

    def configure(self, session_id, params):
        if self._output_snapshot is not None:
            raise RuntimeError("Restore the previous output settings before configuring another segment.")
        self._validate()
        if self.block is None or not self.app.Measurement.Running or self.block.Trigger.Active:
            raise RuntimeError("Measurement must be running and the selected logging trigger must be idle.")
        path = Path(params["temp_path"]).resolve()
        if path.suffix.lower() != ".blf" or path.exists() or not path.parent.is_dir():
            raise ValueError("A new BLF working path is required; existing files are preserved.")
        self.session_id, self.path = session_id, path
        self.attempted = self.stop_confirmed = False
        options = self.block.FileNameOptions
        self._output_snapshot = {"full_name": str(self.block.FullName),
                                 "options": {name: bool(getattr(options, name)) for name in FILE_OPTIONS}}
        self._trace("canoe.output_apply_requested", previous=self._output_snapshot, requested=str(path))
        try:
            for name in FILE_OPTIONS:
                if bool(getattr(options, name)):
                    setattr(options, name, False)
            self.block.FullName = str(path)
            self._validate()
            self._require_single_file()
            if not _same_path(self.block.FullName, path) or not self.app.Measurement.Running:
                raise RuntimeError("CANoe did not accept the exact output path while keeping measurement running.")
        except Exception:
            try:
                self.restore_output(session_id)
            except Exception:
                pass  # The pending snapshot and both failures remain in the journal.
            raise
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
        self._require_single_file()
        running = bool(self.app.Measurement.Running)
        active = bool(self.block.Trigger.Active)
        if active and running and self.path.is_file() and _same_path(self.block.FullName, self.path):
            return "recording", {**self.stats(), "measurement_running": running, "trigger_active": active}
        return "error", {**self.stats(), "measurement_running": running, "trigger_active": active,
                         "error": "Measurement, logging trigger or exact output no longer matches this session"}

    def stop(self, session_id):
        if not self.attempted:
            return self.restore_output(session_id)  # Undo configured output without stopping any foreign trigger.
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
                    try:
                        self.restore_output(session_id)
                    except Exception:
                        pass  # File close remains proven; report restoration separately.
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
