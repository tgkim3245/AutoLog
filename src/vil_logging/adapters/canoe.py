"""Control one newly-created CANoe instance and one existing logging block.

Never attach through the active-object table, save a configuration, create a
logging block, or start/stop measurement. COM stays in the worker's STA thread.
"""

import re
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from vil_logging.diagnostics.canoe_measurement import measurement_diagnostics
from vil_logging.diagnostics.canoe_setup import CanoeActivationError
from vil_logging.storage.blf import FILE_HEADER, inspect_blf
from vil_logging.storage.blf_snapshot import seal_blf
from vil_logging.storage.file_access import ExclusiveFile, observe

FILE_OPTIONS = ("IncrementAtMeasurementStart", "IncrementAfterTrigger",
                "IncrementAfterGrowth", "IncrementAfterDuration")


def _same_path(first, second):
    return str(Path(first).resolve()).casefold() == str(Path(second).resolve()).casefold()


@dataclass
class ActivatedApplication:
    application: object
    process_id: int
    setup: dict


def _create_application():
    from win32com.client import DispatchEx

    from vil_logging.diagnostics.canoe_setup import (
        activation_guard,
        canoe_process_ids,
        ensure_independent_activation,
    )

    with activation_guard():
        setup = ensure_independent_activation()
        before = set(canoe_process_ids())
        app = DispatchEx("CANoe.Application")
        created = set(canoe_process_ids()) - before
        if len(created) != 1:
            raise CanoeActivationError(
                "restart_required", "CANoe did not create exactly one new independent process. "
                "No configuration was opened or replaced. Close existing CANoe windows and reconnect.",
                path=setup["path"], process_ids=sorted(before),
            )
        return ActivatedApplication(app, created.pop(), setup)


class CanoeCapture:
    def __init__(self, *, create_application=None):
        self._create_application = create_application or _create_application
        self.app = self.block = None
        self.cfg = ""
        self.index = 0
        self.session_id = ""
        self.path = None
        self.attempted = False
        self.trigger_stopped = False
        self.stop_confirmed = False
        self.version = ""
        self.canoe_pid = 0
        self.journal = deque(maxlen=40)
        self.emit_trace = None
        self._output_snapshot = None
        self._restore_context = None
        self._selection = None
        self.output_restore_error = ""
        self.file_exclusive = False
        self._inspection = None

    def _trace(self, event, **fields):
        entry = {"event": event, "monotonic": time.monotonic(), **fields}
        self.journal.append(entry)
        if self.emit_trace is not None:
            self.emit_trace(entry)

    def stats(self):
        return {"cfg": self.cfg, "logging_block": self.index, "session_id": self.session_id,
                "canoe_version": self.version, "canoe_pid": self.canoe_pid,
                "path": str(self.path or ""), "start_attempted": self.attempted,
                "trigger_stopped": self.trigger_stopped,
                "stop_confirmed": self.stop_confirmed,
                "file_exclusive": self.file_exclusive,
                "output_restore_pending": self._output_snapshot is not None,
                "output_restore_error": self.output_restore_error,
                "block_validation": "logical_selection_owned_output_idle_blf_refresh", "diagnostics": list(self.journal)}

    def _validate(self, *, allow_idle_output_refresh=False):
        if self.app is None or not _same_path(self.app.Configuration.FullName, self.cfg):
            raise RuntimeError("CANoe configuration changed or window closed. Reconnect while measurement is stopped.")
        if self.block is not None:
            collection = self.app.Configuration.OnlineSetup.LoggingCollection
            count = int(collection.Count)
            expected = self._selection
            if expected is None or count != len(expected["blocks"]):
                self._trace("canoe.block_validation_failed", reason="block_count_changed", count=count,
                            block=self.index, expected=expected)
                raise RuntimeError("Logging block layout changed. Reconnect and select the intended block again.")
            # CANoe can return a new COM identity on every Item(), including
            # during capture. Validate the logical selection and output we own,
            # never Python/IDispatch/IUnknown object identity.
            observed, current = [], None
            for i in range(1, count + 1):
                item = collection.Item(i)
                observed.append({"name": str(item.Name), "path": str(item.FullName)})
                if i == self.index:
                    current = item
            expected_paths = []
            reason = ""
            idle_output_change = None
            restored_output_change = None
            for i, (before, after) in enumerate(zip(expected["blocks"], observed), 1):
                paths = [before["path"]]
                if i == self.index and self._output_snapshot is not None:
                    # Partial COM setters/restoration can leave either path.
                    # Start/query/stop additionally require the exact working
                    # path; restore validates every option before writing.
                    paths = [self._output_snapshot["full_name"], str(self.path)]
                elif (i == self.index and allow_idle_output_refresh
                      and (not self.attempted or self.stop_confirmed)
                      and before["name"] == after["name"]
                      and Path(after["path"]).suffix.lower() == ".blf"
                      and sum(item["name"] == after["name"] for item in observed) == 1
                      and not _same_path(before["path"], after["path"])):
                    # A manual test or CANoe's file-number increment changes
                    # FullName without changing the selected logical block.
                    # Only accept this before taking output ownership, with a
                    # unique name and unchanged cfg/layout/sibling outputs.
                    paths = [after["path"]]
                    idle_output_change = {"previous": before["path"], "current": after["path"]}
                expected_paths.append(paths)
                if (i == self.index and self._restore_context is not None
                        and (not self.attempted or self.trigger_stopped)
                        and before["name"] == after["name"]
                        and sum(item["name"] == after["name"] for item in observed) == 1
                        and not current.Trigger.Active and self._restored_path_matches(after["path"])):
                    paths.append(after["path"])
                    if not _same_path(before["path"], after["path"]):
                        restored_output_change = dict(selected=after, previous=before["path"])
                if before["name"] != after["name"] or not any(_same_path(after["path"], path) for path in paths):
                    reason = "block_layout_or_output_changed"
            selected = observed[self.index - 1]
            matches = sum(item["name"] == selected["name"] and _same_path(item["path"], selected["path"])
                          for item in observed)
            if matches != 1:
                reason = "ambiguous_logging_block"
            if reason:
                self._trace("canoe.block_validation_failed", reason=reason, block=self.index,
                            expected=expected, expected_paths=expected_paths, observed=observed,
                            measurement_running=bool(self.app.Measurement.Running))
                raise RuntimeError("Logging block changed or output was edited externally. "
                                   "Reconnect and select the intended block again.")
            if idle_output_change is not None:
                if current.Trigger.Active:
                    self._trace("canoe.preparation_blocked", reason="manual_recording_active", block=self.index,
                                **idle_output_change)
                    raise RuntimeError("The selected Logging Block is already recording. "
                                       "Stop it manually before AutoLog starts a new segment.")
                expected["blocks"][self.index - 1] = dict(selected)
                self._trace("canoe.idle_output_refreshed", block=self.index, name=selected["name"],
                            **idle_output_change)
            if restored_output_change is not None:
                expected["blocks"][self.index - 1] = dict(selected)
                self._trace("canoe.output_normalized", previous=restored_output_change["previous"],
                            current=selected["path"], block=self.index)
            self.block = current

    def _restored_path_matches(self, value, *, original_only=False):
        """Accept only our idle restore's original path or CANoe's trigger suffix."""
        snapshot = self._restore_context
        if snapshot is None:
            return False
        bases = [snapshot["full_name"]]
        if not original_only and self._output_snapshot is not None:
            bases.append(str(self.path))
        value = Path(value)
        for name in bases:
            if _same_path(value, name):
                return True
            base = Path(name)
            stem = re.sub(r"(?:_T[0-9]+)+$", "", base.stem, flags=re.IGNORECASE)
            if (snapshot["options"]["IncrementAfterTrigger"]
                    and _same_path(value.parent, base.parent)
                    and value.suffix.casefold() == base.suffix.casefold() == ".blf"
                    and any(re.fullmatch(re.escape(root) + r"(?:_T[0-9]{1,20})+", value.stem, re.IGNORECASE)
                            for root in {stem, base.stem})):
                return True
        return False

    def record_failure(self, action, error):
        """Best-effort read-only failure evidence; never mask the command error."""
        observed = {}
        try:
            observed["cfg"] = str(self.app.Configuration.FullName)
            observed["measurement_running"] = bool(self.app.Measurement.Running)
            observed["measurement_diagnostics"] = measurement_diagnostics(self.app, observed["measurement_running"])
        except Exception as diagnostic_error:
            observed["observation_error"] = str(diagnostic_error)
        try:
            collection = self.app.Configuration.OnlineSetup.LoggingCollection
            observed["block_count"] = int(collection.Count)
            if 0 < self.index <= observed["block_count"]:
                block = collection.Item(self.index)
                observed["block"] = {"name": str(block.Name), "path": str(block.FullName),
                                     "trigger_active": bool(block.Trigger.Active)}
        except Exception as diagnostic_error:
            observed["block_observation_error"] = str(diagnostic_error)
        if self.path is not None and action in {"stop", "inspect"}:
            try:
                info = self.path.stat()
                with self.path.open("rb") as source:
                    header = source.read(FILE_HEADER.size)
                observed["file"] = {"bytes": info.st_size, "mtime_ns": info.st_mtime_ns}
                if len(header) == FILE_HEADER.size:
                    fields = FILE_HEADER.unpack(header)
                    observed["file"].update(blf_signature=fields[0] == b"LOGG",
                                            declared_bytes=fields[10], declared_objects=fields[12])
            except Exception as diagnostic_error:
                observed["file_observation_error"] = str(diagnostic_error)
        self._trace("canoe.command_failed", action=action, error=str(error), block=self.index,
                    canoe_pid=self.canoe_pid, observed=observed)

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
            if self.attempted and not (self.trigger_stopped or self.stop_confirmed):
                raise RuntimeError("Normal segment stop must be confirmed before restoring output settings.")
            self._validate()
            if self.block.Trigger.Active:
                raise RuntimeError("Logging trigger became active; output settings were preserved.")
            current_path = str(self.block.FullName)
            if not (_same_path(current_path, self.path) or current_path == snapshot["full_name"]
                    or self._restored_path_matches(current_path)):
                raise RuntimeError("Logging output was edited externally; restoration would overwrite it.")
            options = self.block.FileNameOptions
            # Validate every property before any write. Original values also allow a retry
            # after a COM setter applied a value but failed to acknowledge the call.
            for name, original in snapshot["options"].items():
                if bool(getattr(options, name)) not in (False, original):
                    raise RuntimeError(f"{name} was edited externally; restoration was deferred.")
            self._trace("canoe.output_restore_requested", original=snapshot)
            self._restore_context = snapshot
            # Re-enabling increment modes can itself normalize FullName (_T001).
            # Restore modes first, then the user's filename, and accept that
            # tightly scoped normalization even when CANoe applies it later.
            for name, original in snapshot["options"].items():
                if bool(getattr(options, name)) != original:
                    setattr(options, name, original)
            if not self._restored_path_matches(str(self.block.FullName), original_only=True):
                self.block.FullName = snapshot["full_name"]
            if not self._restored_path_matches(str(self.block.FullName), original_only=True) or any(
                    bool(getattr(options, name)) != value for name, value in snapshot["options"].items()):
                raise RuntimeError("CANoe did not confirm restored output settings.")
            self._validate()
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
                self.canoe_pid = 0
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
            try:
                created = self._create_application()
            except CanoeActivationError as error:
                self._trace("canoe.activation_failed", connection_issue=error.connection_issue,
                            settings_file=error.settings_path, process_ids=error.process_ids)
                raise
            if isinstance(created, ActivatedApplication):
                app = created.application
                self.canoe_pid = created.process_id
                self._trace("canoe.independent_instance_created", canoe_pid=self.canoe_pid,
                            setup=created.setup, requested_cfg=str(cfg))
            else:
                app = created  # Injected test/application factories.
            # DispatchEx must give a fresh application. Never replace any existing project.
            current, running, modified = self._fresh_state(app)
            if current.strip() or running or modified:
                self._trace("canoe.instance_reused", requested=str(cfg), current=current, modified=modified)
                raise CanoeActivationError("restart_required",
                    "CANoe returned an existing configuration; refusing to replace it. "
                    "Independent COM activation is unavailable. Save and close existing CANoe windows, then reconnect. "
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
            self._trace("canoe.configuration_opened", cfg=self.cfg, canoe_pid=self.canoe_pid)
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
        self._selection = {"blocks": [{"name": item["name"], "path": item["path"]} for item in blocks]
                           } if self.block is not None else None
        self.session_id, self.path = "", None
        self._restore_context = None
        self.file_exclusive, self._inspection = False, None
        self.attempted = self.trigger_stopped = self.stop_confirmed = False
        details = {**self.stats(), "blocks": blocks, "selected_block": str(index) if index else "",
                   "measurement_running": bool(self.app.Measurement.Running),
                   "view_only": "view only" in self.version.casefold(),
                   "selection_error": selection_error,
                   "trigger_active": bool(self.block.Trigger.Active) if self.block is not None else None,
                   "automatic_splitting": [name for name in FILE_OPTIONS
                       if self.block is not None and bool(getattr(self.block.FileNameOptions, name))]}
        details["measurement_diagnostics"] = measurement_diagnostics(self.app, details["measurement_running"])
        self._trace("canoe.connected", block=index, measurement_running=details["measurement_running"])
        if not details["measurement_running"]:
            self._trace("canoe.measurement_waiting", measurement_diagnostics=details["measurement_diagnostics"])
        from vil_logging.diagnostics.canoe_hardware import inspect_hardware
        details["hardware"] = inspect_hardware(self.app, self.cfg, params.get("hardware_baseline", ""))
        self._trace("canoe.hardware_checked", hardware=details["hardware"])
        return details

    def prepare(self, params):
        # A logging click is not consent to replace the previously selected
        # block. Validate the selection before connect refreshes it, allowing
        # a verified idle model rebuild or BLF filename change after the user's
        # manual test. Output is frozen as soon as configure takes ownership.
        # Explicit connection checks can deliberately adopt a new selection.
        if self.app is not None:
            self._validate(allow_idle_output_refresh=True)
        details = self.connect(params)
        if self.block is None:
            raise RuntimeError(details["selection_error"] or
                               "Select the intended BLF Logging Block in settings, then check the connection again.")
        self._validate()
        if details["view_only"]:
            raise RuntimeError("CANoe is in View Only mode. Activate a measurement license on the test PC first.")
        if details["hardware"]["status"] == "mismatch":
            raise RuntimeError("CAN hardware mapping differs from the saved reference. Check the device and port in Settings.")
        if params.get("hardware_baseline") and details["hardware"]["status"] == "unavailable":
            raise RuntimeError("The saved CAN hardware reference cannot be verified. Check the device connection in Settings.")
        if not self.app.Measurement.Running:
            diagnostics = details["measurement_diagnostics"]
            self._trace("canoe.preparation_blocked", reason="measurement_not_running",
                        measurement_diagnostics=diagnostics)
            missing = ", ".join(diagnostics["missing_options"])
            history = f" CANoe Write history reports missing options: {missing} (may be an earlier attempt)." if missing else ""
            raise RuntimeError("Start measurement (F9) in the AutoLog-created CANoe window after checking channel mapping "
                               "and all bus-option licenses required by this cfg. If F9 fails, review CANoe's Write window. "
                               "Confirm CAN reception in Trace, then check the connection again." + history)
        if self.block.Trigger.Active:
            raise RuntimeError("The selected Logging Block is already recording. Stop it manually before AutoLog starts a new segment.")
        self._trace("canoe.prepared", block=self.index)
        return {**details, **self.stats()}

    def configure(self, session_id, params):
        if self.attempted and not self.stop_confirmed:
            raise RuntimeError("Resolve the previous recording before configuring another segment.")
        if self._output_snapshot is not None:
            raise RuntimeError("Restore the previous output settings before configuring another segment.")
        self._validate(allow_idle_output_refresh=True)
        if self.block is None or not self.app.Measurement.Running or self.block.Trigger.Active:
            raise RuntimeError("Measurement must be running and the selected logging trigger must be idle.")
        path = Path(params["temp_path"]).resolve()
        if path.suffix.lower() != ".blf" or path.exists() or not path.parent.is_dir():
            raise ValueError("A new BLF working path is required; existing files are preserved.")
        self.session_id, self.path = session_id, path
        self._restore_context = None
        self.file_exclusive, self._inspection = False, None
        self.attempted = self.trigger_stopped = self.stop_confirmed = False
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
        self._trace("canoe.output_confirmed", path=str(path), block=self.index,
                    name=str(self.block.Name), block_validation="logical_selection_and_owned_output")
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
        self.trigger_stopped = self.stop_confirmed = False
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
        started = time.monotonic()
        self._validate()
        if not self.trigger_stopped and not _same_path(self.block.FullName, self.path):
            raise RuntimeError("Logging output changed externally; refusing to stop another segment.")
        if self.trigger_stopped:
            if self.block.Trigger.Active:
                raise RuntimeError("Logging restarted after this segment stopped; refusing to stop another recording.")
        else:
            self._trace("canoe.trigger_stop_requested")
            if self.block.Trigger.Active:
                self.block.Trigger.Stop()
        deadline = time.monotonic() + 28
        restore_attempts = 0
        while time.monotonic() < deadline:
            self._validate()
            active = bool(self.block.Trigger.Active)
            if self.trigger_stopped and active:
                raise RuntimeError("Logging restarted after this segment stopped; output settings were preserved.")
            if not active:
                if not self.trigger_stopped:
                    self.trigger_stopped = True
                    self._trace("canoe.trigger_stopped", elapsed_ms=round((time.monotonic() - started) * 1000))
                if self._output_snapshot is not None and restore_attempts < 3:
                    restore_attempts += 1
                    try:
                        self.restore_output(session_id)
                    except Exception:
                        if restore_attempts < 3:
                            time.sleep(.05)
                            continue
                        # Settings restoration and a complete BLF are separate
                        # outcomes. Preserve conflicts; never stop a foreign log.
                if self.block.Trigger.Active:
                    raise RuntimeError("Logging restarted during output restoration; refusing to certify closure.")
                try:
                    with ExclusiveFile(self.path, observe(self.path)):
                        pass
                except (OSError, ValueError) as error:
                    self._trace("canoe.file_handle_retained", error=str(error),
                                output_restore_pending=self._output_snapshot is not None,
                                next_step="validate_complete_stable_snapshot")
                else:
                    self.file_exclusive = True
                self.stop_confirmed = True  # Trigger stop; file completeness is checked by inspect_file.
                self._trace("canoe.segment_stopped", measurement_running=bool(self.app.Measurement.Running),
                            file_exclusive=self.file_exclusive,
                            elapsed_ms=round((time.monotonic() - started) * 1000))
                return self.stats()
            time.sleep(.05)
        raise TimeoutError("CANoe logging trigger did not stop within its time limit")

    def inspect_file(self, session_id):
        if session_id != self.session_id or not self.stop_confirmed:
            raise RuntimeError("Inspect only this session's normally stopped BLF.")
        self._validate()
        if self.block.Trigger.Active:
            raise RuntimeError("Logging restarted; refusing to archive a live recording")
        if self._inspection is None:
            settle_deadline = time.monotonic() + 2
            waiting_reported = False
            while True:
                self._validate()
                if self.block.Trigger.Active:
                    raise RuntimeError("Logging restarted during inspection; capture was preserved")
                try:
                    try:
                        with ExclusiveFile(self.path, observe(self.path)):
                            pass
                    except OSError as error:
                        if getattr(error, "winerror", None) != 32:
                            raise
                        result = seal_blf(self.path)
                        self._trace("canoe.snapshot_sealed", path=str(self.path), bytes=result["bytes"],
                                    sha256=result["retained_source"]["sha256"], objects=result["object_count"])
                    else:
                        result = {**inspect_blf(self.path), "closure_evidence": "exclusive_access"}
                except (OSError, ValueError) as error:
                    if (time.monotonic() >= settle_deadline or isinstance(error, OSError)
                            and getattr(error, "winerror", None) != 32):
                        raise
                    if not waiting_reported:
                        self._trace("canoe.file_finalizing", error=str(error))
                        waiting_reported = True
                    time.sleep(.1)
                else:
                    break
            self._validate()
            if self.block.Trigger.Active:
                raise RuntimeError("Logging restarted during inspection; capture was preserved")
            self._inspection = result
        return {**self._inspection, **self.stats()}
