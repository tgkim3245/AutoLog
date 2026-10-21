"""COM doubles exercise ownership, target revalidation and measurement preservation."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from vil_logging.adapters.canoe import CanoeCapture
from vil_logging.storage.blf import FILE_HEADER


def empty_blf():
    return FILE_HEADER.pack(b"LOGG", 144, *([0] * 8), 144, 144, 0, 0, *([0] * 16)).ljust(144, b"\0")


class Trigger:
    def __init__(self, block):
        self.block = block
        self.Active = False
        self.starts = self.stops = 0

    def Start(self):
        self.starts += 1
        self.Active = True
        Path(self.block.FullName).write_bytes(b"LOGG" + bytes(140))

    def Stop(self):
        self.stops += 1
        self.Active = False
        Path(self.block.FullName).write_bytes(empty_blf())


class Block:
    def __init__(self, name):
        self.Name = "Logging"
        self.FullName = name
        self.Trigger = Trigger(self)
        self.FileNameOptions = SimpleNamespace(IncrementAtMeasurementStart=False,
                                               IncrementAfterTrigger=False, IncrementAfterGrowth=False,
                                               IncrementAfterDuration=False)


class FreshComProxy:
    """A different wrapper/IUnknown per Item() over the same CANoe block."""

    def __init__(self, target):
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_oleobj_", SimpleNamespace(QueryInterface=lambda _iid: object()))

    def __getattr__(self, name):
        return getattr(self._target, name)

    def __setattr__(self, name, value):
        setattr(self._target, name, value)


class Application:
    def __init__(self, count=1):
        self.blocks = [Block(f"original_{i}.blf") for i in range(count)]
        self.fresh_proxies = False
        self.Configuration = SimpleNamespace(FullName="", Modified=False, OnlineSetup=SimpleNamespace(
            LoggingCollection=SimpleNamespace(Count=count, Item=self.item)))
        self.Measurement = SimpleNamespace(Running=False)
        self.open_calls = []

    def item(self, index):
        block = self.blocks[index - 1]
        return FreshComProxy(block) if self.fresh_proxies else block

    def Open(self, path, auto_save, prompt):
        self.open_calls.append((path, auto_save, prompt))
        self.Configuration.FullName = path


@pytest.fixture
def fixture(tmp_path):
    cfg = tmp_path / "user.cfg"
    cfg.write_bytes(b"original configuration, never saved by AutoLog")
    app = Application()
    capture = CanoeCapture(create_application=lambda: app)
    return capture, app, {"cfg_path": str(cfg)}, tmp_path


def prepared(fixture):
    capture, app, params, root = fixture
    capture.connect(params)
    app.Measurement.Running = True  # Explicit simulated user action, never an adapter call.
    capture.prepare(params)
    path = root / "AutoLog_1.blf"
    capture.configure("s1", {"temp_path": str(path)})
    return capture, app, path


def test_three_segments_keep_measurement_and_original_configuration(fixture):
    capture, app, params, root = fixture
    capture.connect(params)
    app.Measurement.Running = True
    for number in range(3):
        capture.prepare(params)
        path = root / f"capture_{number}.blf"
        session = f"session-{number}"
        capture.configure(session, {"temp_path": str(path)})
        capture.start(session, {"temp_path": str(path)})
        assert capture.query()[0] == "recording"
        capture.stop(session)
        assert capture.inspect_file(session)["actual_format"] == "blf"
        assert app.Measurement.Running
    assert len(app.open_calls) == 1
    assert app.open_calls[0][1:] == (False, True)
    assert app.blocks[0].Trigger.starts == app.blocks[0].Trigger.stops == 3
    assert Path(params["cfg_path"]).read_bytes() == b"original configuration, never saved by AutoLog"


def test_fresh_com_proxies_record_three_segments_without_touching_other_block(tmp_path):
    cfg = tmp_path / "can.cfg"
    cfg.write_bytes(b"original configuration")
    app = Application(2)
    app.fresh_proxies = True
    block, other = app.blocks
    block.Name = "CAN_Logging"
    other.Name, other.FullName = "ETH_Logging", "original.pcapng"
    block.FileNameOptions.IncrementAfterTrigger = True
    capture = CanoeCapture(create_application=lambda: app)
    params = {"cfg_path": str(cfg), "logging_block": "1"}
    capture.connect(params)
    app.Measurement.Running = True
    for number in range(3):
        capture.prepare(params)
        session, path = f"session-{number}", tmp_path / f"capture_{number}.blf"
        capture.configure(session, {"temp_path": str(path)})
        assert not block.FileNameOptions.IncrementAfterTrigger
        capture.start(session, {"temp_path": str(path)})
        assert capture.query()[0] == "recording"
        capture.stop(session)
        assert capture.inspect_file(session)["actual_format"] == "blf"
        assert block.FullName == "original_0.blf" and block.FileNameOptions.IncrementAfterTrigger
        assert not capture.stats()["output_restore_pending"]
    assert block.Trigger.starts == block.Trigger.stops == 3
    assert other.Trigger.starts == other.Trigger.stops == 0
    assert other.FullName == "original.pcapng"
    assert cfg.read_bytes() == b"original configuration"
    assert app.Measurement.Running and len(app.open_calls) == 1


@pytest.mark.parametrize("role", ["can", "diag"])
@pytest.mark.parametrize("fresh_proxies", [False, True])
def test_manual_recording_filename_changes_allow_three_segments(tmp_path, role, fresh_proxies):
    cfg = tmp_path / f"{role}.cfg"
    cfg.write_bytes(b"user configuration")
    app = Application(2 if role == "can" else 1)
    app.fresh_proxies = fresh_proxies
    block = app.blocks[0]
    block.Name = "CAN_Logging" if role == "can" else "Logging"
    if role == "can":
        app.blocks[1].Name, app.blocks[1].FullName = "ETH_Logging", "untouched.pcapng"
    capture = CanoeCapture(create_application=lambda: app)
    params = {"cfg_path": str(cfg), "logging_block": "1"}
    capture.connect(params)  # The cfg's original filename is observed before the manual test.
    app.Measurement.Running = True
    for number in range(3):
        manual = tmp_path / f"manual_{number:03}.blf"
        manual.write_bytes(empty_blf())
        block.FullName = str(manual)  # Manual recording / CANoe filename increment, then stopped.
        block.FileNameOptions.IncrementAfterTrigger = True
        capture.prepare(params)
        path, session = tmp_path / f"segment_{number}.blf", f"{role}-{number}"
        capture.configure(session, {"temp_path": str(path)})
        capture.start(session, {"temp_path": str(path)})
        assert capture.query()[0] == "recording"
        capture.stop(session)
        assert capture.inspect_file(session)["actual_format"] == "blf"
        assert block.FullName == str(manual) and block.FileNameOptions.IncrementAfterTrigger
        assert manual.read_bytes() == empty_blf()
        assert not capture.stats()["output_restore_pending"]
    assert block.Trigger.starts == block.Trigger.stops == 3
    assert len([row for row in capture.journal if row["event"] == "canoe.idle_output_refreshed"]) >= 1
    if role == "can":
        assert app.blocks[1].FullName == "untouched.pcapng"
        assert app.blocks[1].Trigger.starts == app.blocks[1].Trigger.stops == 0
    assert len(app.open_calls) == 1 and app.Measurement.Running
    assert cfg.read_bytes() == b"user configuration"


def test_idle_filename_change_between_prepare_and_configure_restores_latest_path(fixture):
    capture, app, params, root = fixture
    capture.connect(params)
    app.Measurement.Running = True
    capture.prepare(params)
    manual = str(root / "manual_increment_003.blf")
    app.blocks[0].FullName = manual
    path = root / "segment.blf"
    capture.configure("segment", {"temp_path": str(path)})
    capture.stop("segment")  # Cancellation before Start also restores the most recent manual path.
    assert app.blocks[0].FullName == manual
    assert app.blocks[0].Trigger.starts == app.blocks[0].Trigger.stops == 0
    assert not capture.stats()["output_restore_pending"]


@pytest.mark.parametrize("stage", ["prepare", "configure"])
def test_changed_manual_filename_while_active_is_not_adopted_or_stopped(fixture, stage):
    capture, app, params, root = fixture
    capture.connect(params)
    app.Measurement.Running = True
    if stage == "configure":
        capture.prepare(params)
    block = app.blocks[0]
    block.FullName = str(root / "manual_active.blf")
    block.Trigger.Active = True
    args = (params,) if stage == "prepare" else ("segment", {"temp_path": str(root / "segment.blf")})
    with pytest.raises(RuntimeError, match="already recording"):
        getattr(capture, stage)(*args)
    assert capture._selection["blocks"][0]["path"] == "original_0.blf"
    assert block.FullName == str(root / "manual_active.blf") and block.Trigger.Active
    assert block.Trigger.starts == block.Trigger.stops == 0
    assert not capture.stats()["output_restore_pending"]
    block.Trigger.Active = False  # Manual stop by the user, not AutoLog.
    capture.prepare(params)
    assert capture._selection["blocks"][0]["path"] == block.FullName


@pytest.mark.parametrize("change", ["sibling_path", "duplicate_name"])
def test_idle_filename_refresh_does_not_hide_layout_or_sibling_changes(fixture, change):
    capture, app, params, _ = fixture
    other = Block("untouched.pcapng")
    other.Name = "ETH_Logging" if change == "sibling_path" else "Logging"
    app.blocks.append(other)
    app.Configuration.OnlineSetup.LoggingCollection.Count = 2
    params = {**params, "logging_block": "1"}
    capture.connect(params)
    app.Measurement.Running = True
    app.blocks[0].FullName = "manual_increment_002.blf"
    if change == "sibling_path":
        other.FullName = "externally_changed.pcapng"
    with pytest.raises(RuntimeError, match="changed"):
        capture.prepare(params)
    assert capture._selection["blocks"][0]["path"] == "original_0.blf"
    assert all(block.Trigger.starts == block.Trigger.stops == 0 for block in app.blocks)


@pytest.mark.parametrize("status", ["mismatch", "unavailable"])
def test_saved_hardware_reference_blocks_start_when_unverified(fixture, monkeypatch, status):
    capture, app, params, _ = fixture
    monkeypatch.setattr("vil_logging.diagnostics.canoe_hardware.inspect_hardware",
                        lambda *_args: {"status": status})
    capture.connect(params)
    app.Measurement.Running = True
    with pytest.raises(RuntimeError, match="hardware"):
        capture.prepare({**params, "hardware_baseline": "saved-reference"})
    assert not app.blocks[0].Trigger.starts


def test_existing_configuration_is_never_replaced(fixture):
    capture, app, params, _ = fixture
    app.Configuration.FullName = "C:/unrelated.cfg"
    with pytest.raises(RuntimeError, match="existing configuration"):
        capture.connect(params)
    assert not app.open_calls


def test_unsaved_untitled_configuration_is_never_replaced(fixture):
    capture, app, params, _ = fixture
    app.Configuration.Modified = True
    with pytest.raises(RuntimeError, match="existing configuration"):
        capture.connect(params)
    assert not app.open_calls and app.Configuration.Modified


def test_multiple_blocks_require_selection_and_other_trigger_is_untouched(tmp_path):
    cfg = tmp_path / "test.cfg"
    cfg.write_bytes(b"test")
    app = Application(count=2)
    capture = CanoeCapture(create_application=lambda: app)
    params = {"cfg_path": str(cfg)}
    assert capture.connect(params)["selected_block"] == ""
    app.Measurement.Running = True
    with pytest.raises(RuntimeError, match="Select"):
        capture.prepare(params)
    capture.prepare({**params, "logging_block": "2"})
    path = tmp_path / "segment.blf"
    capture.configure("s1", {"temp_path": str(path)})
    capture.start("s1", {"temp_path": str(path)})
    capture.stop("s1")
    assert app.blocks[0].FullName == "original_0.blf"
    assert app.blocks[0].Trigger.starts == app.blocks[0].Trigger.stops == 0


@pytest.mark.parametrize("fresh_proxies", [False, True])
@pytest.mark.parametrize("fault", ["configuration", "block", "filename", "measurement", "splitting", "name", "sibling"])
def test_external_changes_prevent_start(fixture, fault, fresh_proxies):
    capture, app, path = prepared(fixture)
    app.fresh_proxies = fresh_proxies
    block = app.blocks[0]
    if fault == "configuration":
        app.Configuration.FullName = "C:/another.cfg"
    elif fault == "block":
        app.blocks[0] = Block("other.blf")
    elif fault == "filename":
        block.FullName = "other.blf"
    elif fault == "measurement":
        app.Measurement.Running = False
    elif fault == "splitting":
        block.FileNameOptions.IncrementAfterTrigger = True
    elif fault == "name":
        block.Name = "Another block"
    else:
        app.blocks.append(Block("another.blf"))
        app.Configuration.OnlineSetup.LoggingCollection.Count = 2
    with pytest.raises(RuntimeError):
        capture.start("s1", {"temp_path": str(path)})
    assert block.Trigger.starts == 0


@pytest.mark.parametrize("change", ["block", "configuration"])
def test_preparation_cannot_silently_adopt_an_external_replacement(fixture, change):
    capture, app, params, root = fixture
    capture.connect(params)
    app.Measurement.Running = True
    if change == "block":
        app.blocks[0] = Block("replacement.blf")
        app.blocks[0].Name = "Replacement logging block"
    else:
        app.Configuration.FullName = str(root / "another.cfg")
    with pytest.raises(RuntimeError, match="changed"):
        capture.prepare(params)
    assert len(app.open_calls) == 1
    assert app.blocks[0].Trigger.starts == 0
    if change == "block":
        capture.connect(params)  # Explicit connection confirmation adopts the changed block.
        capture.prepare(params)
        assert capture.block is app.blocks[0]


def test_no_measurement_or_existing_recording_blocks_preparation(fixture):
    capture, app, params, _ = fixture
    with pytest.raises(RuntimeError, match="Start measurement"):
        capture.prepare(params)
    app.Measurement.Running = True
    app.blocks[0].Trigger.Active = True
    with pytest.raises(RuntimeError, match="already recording"):
        capture.prepare(params)
    app.blocks[0].Trigger.Active = False
    app.blocks[0].FileNameOptions.IncrementAfterGrowth = True
    assert capture.prepare(params)["automatic_splitting"] == ["IncrementAfterGrowth"]


def test_idle_model_rebuild_after_manual_measurement_reacquires_exact_block(fixture):
    capture, app, params, root = fixture
    capture.connect(params)
    old = app.blocks[0]
    old.FileNameOptions.IncrementAfterGrowth = True
    capture.connect(params)  # Explicitly confirm this output option before F9.
    replacement = Block(old.FullName)
    replacement.FileNameOptions.IncrementAfterGrowth = True
    app.blocks[0] = replacement  # A new COM model, with the same logical selection.
    app.Measurement.Running = True
    capture.prepare(params)
    path = root / "rebound.blf"
    capture.configure("rebound", {"temp_path": str(path)})
    capture.start("rebound", {"temp_path": str(path)})
    capture.stop("rebound")
    assert capture.block is replacement
    assert replacement.Trigger.starts == replacement.Trigger.stops == 1
    assert old.Trigger.starts == old.Trigger.stops == 0
    assert replacement.FullName == old.FullName
    assert replacement.FileNameOptions.IncrementAfterGrowth
    assert not capture.stats()["output_restore_pending"]


def test_disconnected_idle_com_handle_can_be_reacquired(fixture):
    capture, app, params, _ = fixture
    capture.connect(params)
    old = app.blocks[0]
    app.blocks[0] = Block(old.FullName)
    app.Measurement.Running = True
    class Disconnected:
        def __getattr__(self, _name):
            raise RuntimeError("COM object disconnected during model rebuild")
    capture.block = Disconnected()
    capture.prepare(params)
    assert capture.block is app.blocks[0]


@pytest.mark.parametrize("change", ["name", "format", "count", "order", "ambiguous"])
def test_idle_rebuild_never_adopts_changed_or_ambiguous_selection(fixture, change):
    capture, app, params, _ = fixture
    if change in {"order", "ambiguous"}:
        app.blocks.append(Block("second.blf" if change == "order" else app.blocks[0].FullName))
        app.Configuration.OnlineSetup.LoggingCollection.Count = 2
        params = {**params, "logging_block": "1"}
    capture.connect(params)
    old = app.blocks[0]
    app.blocks[0] = Block(old.FullName)
    if change == "name":
        app.blocks[0].Name = "Different logging block"
    elif change == "format":
        app.blocks[0].FullName = "different.pcapng"
    elif change == "count":
        app.blocks.append(Block("second.blf"))
        app.Configuration.OnlineSetup.LoggingCollection.Count = 2
    elif change == "order":
        app.blocks.reverse()
    app.Measurement.Running = True
    with pytest.raises(RuntimeError, match="changed"):
        capture.prepare(params)
    assert capture.block is old
    assert all(not block.Trigger.starts for block in app.blocks)
    assert any(row["event"] == "canoe.block_validation_failed" for row in capture.journal)


@pytest.mark.parametrize("active", [False, True])
def test_owned_output_accepts_fresh_proxy_during_start_and_stop(fixture, active):
    capture, app, path = prepared(fixture)
    old = app.blocks[0]
    if active:
        capture.start("s1", {"temp_path": str(path)})
    app.fresh_proxies = True
    if not active:
        capture.start("s1", {"temp_path": str(path)})
    assert capture.query()[0] == "recording"
    capture.stop("s1")
    assert old.Trigger.starts == old.Trigger.stops == 1
    assert old.FullName == "original_0.blf"
    assert not capture.stats()["output_restore_pending"]


def test_failed_preparation_records_measurement_and_option_history(fixture):
    capture, app, params, _ = fixture
    app.UI = SimpleNamespace(Write=SimpleNamespace(Text=(
        "[E]\t[System]\tRequired bus system options:\n"
        "[E]\t[System]\tCAN (available)\n[E]\t[System]\tEthernet (missing)\n"
        "[E]\t[System]\tMeasurement was halted.")))
    with pytest.raises(RuntimeError, match="Ethernet") as failed:
        capture.prepare(params)
    capture.record_failure("prepare", failed.value)
    failure = capture.journal[-1]
    assert failure["action"] == "prepare"
    assert not failure["observed"]["measurement_running"]
    assert failure["observed"]["measurement_diagnostics"]["missing_options"] == ["Ethernet"]
    assert "earlier attempt" in str(failed.value)
    assert not app.blocks[0].Trigger.starts


def test_foreign_session_stop_and_inspect_are_rejected(fixture):
    capture, app, path = prepared(fixture)
    capture.start("s1", {"temp_path": str(path)})
    with pytest.raises(RuntimeError, match="different"):
        capture.stop("s2")
    with pytest.raises(RuntimeError, match="normally stopped"):
        capture.inspect_file("s1")
    assert app.blocks[0].Trigger.stops == 0
    capture.stop("s1")


def test_stop_never_touches_a_trigger_without_an_owned_start(fixture):
    capture, app, params, _ = fixture
    capture.connect(params)
    app.blocks[0].Trigger.Active = True
    capture.stop("not-our-session")
    assert app.blocks[0].Trigger.stops == 0


def test_real_can_layout_selects_only_blf_and_reports_names_and_formats(tmp_path):
    cfg = tmp_path / "can.cfg"
    cfg.write_bytes(b"test")
    app = Application(2)
    app.blocks[0].Name = "CAN_Logging"
    app.blocks[1].Name = "ETH_Logging"
    app.blocks[1].FullName = "traffic.pcapng"
    capture = CanoeCapture(create_application=lambda: app)
    params = {"cfg_path": str(cfg)}
    details = capture.connect(params)
    assert details["selected_block"] == "1"
    assert details["blocks"][0]["name"] == "CAN_Logging"
    assert details["blocks"][1] == {"id": "2", "name": "ETH_Logging", "path": "traffic.pcapng",
                                    "format": "pcapng", "compatible": False}
    for selection in ["2", "99"]:
        details = capture.connect({**params, "logging_block": selection})
        assert details["selected_block"] == "" and details["selection_error"]
        assert len(details["blocks"]) == 2
    assert app.blocks[1].FullName == "traffic.pcapng"


def test_view_only_is_reported_and_prevents_recording(fixture):
    capture, app, params, _ = fixture
    app.Version = SimpleNamespace(FullName="CANoe 19.3.118 (View Only)")
    assert capture.connect(params)["view_only"]
    app.Measurement.Running = True  # Even inconsistent state must not advertise readiness.
    with pytest.raises(RuntimeError, match="license"):
        capture.prepare(params)
    assert not capture.stats()["output_restore_pending"]


def test_automatic_filename_options_are_temporary_for_three_segments(fixture):
    capture, app, params, root = fixture
    block = app.blocks[0]
    original = block.FullName
    block.FileNameOptions.IncrementAfterTrigger = True
    block.FileNameOptions.IncrementAfterGrowth = True
    capture.connect(params)
    app.Measurement.Running = True
    for number in range(3):
        capture.prepare(params)
        session, path = f"s{number}", root / f"segment{number}.blf"
        capture.configure(session, {"temp_path": str(path)})
        assert not block.FileNameOptions.IncrementAfterTrigger
        assert not block.FileNameOptions.IncrementAfterGrowth
        capture.start(session, {"temp_path": str(path)})
        capture.stop(session)
        assert capture.inspect_file(session)["object_count"] == 0
        assert block.FullName == original
        assert block.FileNameOptions.IncrementAfterTrigger
        assert block.FileNameOptions.IncrementAfterGrowth
        assert not capture.stats()["output_restore_pending"]
        assert app.Measurement.Running


@pytest.mark.parametrize("fresh_proxies", [False, True])
def test_cancel_after_configuration_restores_without_touching_trigger(fixture, fresh_proxies):
    capture, app, path = prepared(fixture)
    app.fresh_proxies = fresh_proxies
    capture.restore_output("s1")
    assert app.blocks[0].FullName == "original_0.blf"
    assert not path.exists()
    assert app.blocks[0].Trigger.starts == app.blocks[0].Trigger.stops == 0


@pytest.mark.parametrize("fresh_proxies", [False, True])
def test_output_apply_failure_rolls_back_partial_option_changes(fixture, fresh_proxies):
    capture, app, params, root = fixture
    app.fresh_proxies = fresh_proxies

    class RejectGrowth:
        IncrementAtMeasurementStart = False
        IncrementAfterTrigger = True
        IncrementAfterDuration = False

        @property
        def IncrementAfterGrowth(self):
            return True

        @IncrementAfterGrowth.setter
        def IncrementAfterGrowth(self, value):
            raise RuntimeError("injected property refusal")

    block = app.blocks[0]
    block.FileNameOptions = RejectGrowth()
    capture.connect(params)
    app.Measurement.Running = True
    with pytest.raises(RuntimeError, match="property refusal"):
        capture.configure("s1", {"temp_path": str(root / "fail.blf")})
    assert block.FileNameOptions.IncrementAfterTrigger
    assert block.FullName == "original_0.blf"
    assert not capture.stats()["output_restore_pending"]


@pytest.mark.parametrize("fresh_proxies", [False, True])
def test_external_output_edit_is_preserved_and_blocks_next_configuration(fixture, fresh_proxies):
    capture, app, path = prepared(fixture)
    app.fresh_proxies = fresh_proxies
    app.blocks[0].FullName = "user-edited.blf"
    with pytest.raises(RuntimeError, match="externally"):
        capture.restore_output("s1")
    with pytest.raises(RuntimeError, match="previous output"):
        capture.configure("s2", {"temp_path": str(path.with_name("next.blf"))})
    assert app.blocks[0].FullName == "user-edited.blf"
    assert capture.stats()["output_restore_pending"]


@pytest.mark.parametrize("fault", ["name", "path", "sibling_path", "order", "ambiguity"])
def test_recording_logical_changes_never_stop_a_foreign_block(tmp_path, fault):
    cfg = tmp_path / "can.cfg"
    cfg.write_bytes(b"original")
    app = Application(2)
    app.fresh_proxies = True
    app.blocks[0].Name, app.blocks[1].Name = "CAN_Logging", "Other"
    capture = CanoeCapture(create_application=lambda: app)
    params = {"cfg_path": str(cfg), "logging_block": "1"}
    capture.connect(params)
    app.Measurement.Running = True
    capture.prepare(params)
    path = tmp_path / "owned.blf"
    capture.configure("s1", {"temp_path": str(path)})
    capture.start("s1", {"temp_path": str(path)})
    owned, other = app.blocks
    if fault == "name":
        owned.Name = "Externally renamed"
    elif fault == "path":
        owned.FullName = "foreign.blf"
    elif fault == "sibling_path":
        other.FullName = "edited.blf"
    elif fault == "order":
        app.blocks.reverse()
    else:
        other.Name, other.FullName = owned.Name, owned.FullName
    with pytest.raises(RuntimeError, match="changed"):
        capture.stop("s1")
    assert owned.Trigger.stops == other.Trigger.stops == 0
    assert capture.stats()["output_restore_pending"]


def test_normal_file_close_survives_restore_failure_and_keeps_evidence(fixture, monkeypatch):
    capture, app, path = prepared(fixture)
    capture.start("s1", {"temp_path": str(path)})
    real_restore = capture.restore_output

    def fail_restore_only(session_id):
        capture.output_restore_error = "injected restore failure"
        raise RuntimeError(capture.output_restore_error)

    monkeypatch.setattr(capture, "restore_output", fail_restore_only)
    details = capture.stop("s1")
    assert details["stop_confirmed"] and details["output_restore_pending"]
    assert "injected restore failure" in details["output_restore_error"]
    assert capture.inspect_file("s1")["actual_format"] == "blf"
    monkeypatch.setattr(capture, "restore_output", real_restore)
    capture.restore_output("s1")
    assert app.blocks[0].FullName == "original_0.blf"


class RetainedWriterBlock(Block):
    """A stopped trigger retains its writer until the idle filename changes."""

    def __init__(self, name):
        self.writer = None
        super().__init__(name)
        start = self.Trigger.Start

        def begin():
            start()
            self.writer = Path(self.FullName).open("r+b")

        def pause():
            self.Trigger.stops += 1
            self.Trigger.Active = False
            self.writer.seek(0)
            self.writer.write(empty_blf())
            self.writer.flush()

        self.Trigger.Start, self.Trigger.Stop = begin, pause

    @property
    def FullName(self):
        return self._full_name

    @FullName.setter
    def FullName(self, value):
        if self.writer is not None and value != self._full_name:
            self.writer.close()
            self.writer = None
        self._full_name = value


class NormalizingRestoreBlock(RetainedWriterBlock):
    """CANoe applies trigger numbering two FullName reads after a setter."""

    def __init__(self, name):
        self.armed = False
        self.append_number = False
        self.pending = None
        self.reads = self.counter = 0
        super().__init__(name)
        block = self

        class Options(SimpleNamespace):
            def __setattr__(self, key, value):
                previous = getattr(self, key, False)
                super().__setattr__(key, value)
                if key == "IncrementAfterTrigger" and value and not previous and block.armed:
                    block.normalize(block._full_name)

        self.FileNameOptions = Options(IncrementAtMeasurementStart=False, IncrementAfterTrigger=True,
                                       IncrementAfterGrowth=False, IncrementAfterDuration=False)

    def normalize(self, value):
        import re
        path = Path(value)
        self.counter += 1
        stem = path.stem if self.append_number else re.sub(r"_T[0-9]+$", "", path.stem)
        self.pending = str(path.with_name(f"{stem}_T{self.counter:03d}.blf"))
        self.reads = 0

    @property
    def FullName(self):
        if self.pending is not None:
            self.reads += 1
            if self.reads >= 2:
                self._full_name, self.pending = self.pending, None
        return self._full_name

    @FullName.setter
    def FullName(self, value):
        RetainedWriterBlock.FullName.fset(self, value)
        if self.armed and self.FileNameOptions.IncrementAfterTrigger:
            self.normalize(value)


@pytest.mark.parametrize("name,append", [("manual.blf", False), ("manual_T009.blf", False),
                                        ("any name_T002_T001.blf", True), ("임의 초기 이름.blf", True)])
def test_delayed_trigger_numbering_during_restore_allows_three_closed_segments(fixture, name, append):
    capture, app, params, root = fixture
    app.blocks[0] = block = NormalizingRestoreBlock(str(root / name))
    block.append_number = append
    app.fresh_proxies = True
    capture.connect(params)
    app.Measurement.Running = True
    try:
        for number in range(3):
            capture.prepare(params)
            path, session = root / f"segment_{number}.blf", f"segment-{number}"
            capture.configure(session, {"temp_path": str(path)})
            capture.start(session, {"temp_path": str(path)})
            block.armed = True
            result = capture.stop(session)
            assert result["stop_confirmed"] and not result["output_restore_pending"]
            assert capture.inspect_file(session)["actual_format"] == "blf"
            assert block.writer is None and block.FileNameOptions.IncrementAfterTrigger
            assert Path(block.FullName).parent == root and Path(block.FullName).name.startswith(Path(name).stem.split("_T")[0])
            assert app.Measurement.Running
        assert block.Trigger.starts == block.Trigger.stops == 3
        assert any(row["event"] == "canoe.output_normalized" for row in capture.journal)
    finally:
        if block.writer:
            block.writer.close()


def test_trigger_suffix_is_not_accepted_as_external_output_before_our_restore(fixture):
    capture, app, path = prepared(fixture)
    capture.start("s1", {"temp_path": str(path)})
    app.blocks[0].FullName = "original_0_T001.blf"
    app.blocks[0].Trigger.Active = False
    with pytest.raises(RuntimeError, match="changed"):
        capture.stop("s1")
    assert app.blocks[0].Trigger.stops == 0


def test_retained_blf_header_can_finish_shortly_after_trigger_stop(fixture, monkeypatch):
    capture, app, path = prepared(fixture)
    capture.start("s1", {"temp_path": str(path)})
    capture.stop("s1")
    clock = SimpleNamespace(now=0.)
    with path.open("r+b") as writer:
        writer.write(b"LOGG" + bytes(140))
        writer.flush()

        def settle(delay):
            clock.now += delay
            writer.seek(0)
            writer.write(empty_blf())
            writer.flush()

        monkeypatch.setattr("vil_logging.adapters.canoe.time", SimpleNamespace(
            monotonic=lambda: clock.now, sleep=settle))
        checked = capture.inspect_file("s1")
        assert checked["blf_snapshot_path"] and checked["bytes"] == 144
        assert clock.now == .1
        assert any(row["event"] == "canoe.file_finalizing" for row in capture.journal)


def test_incomplete_blf_is_not_certified_even_when_trigger_has_stopped(fixture, monkeypatch):
    capture, app, path = prepared(fixture)
    capture.start("s1", {"temp_path": str(path)})
    capture.stop("s1")
    path.write_bytes(b"LOGG" + bytes(140))
    clock = SimpleNamespace(now=0.)
    monkeypatch.setattr("vil_logging.adapters.canoe.time", SimpleNamespace(
        monotonic=lambda: clock.now, sleep=lambda delay: setattr(clock, "now", clock.now + delay)))
    with path.open("r+b"):
        with pytest.raises(ValueError):
            capture.inspect_file("s1")
        assert capture._inspection is None and 2 <= clock.now < 3
    assert path.exists() and not path.with_name(path.name + ".sealed").exists()
    capture.record_failure("inspect", ValueError("incomplete"))
    assert capture.journal[-1]["observed"]["file"]["declared_bytes"] == 0


class NextTriggerFinalizesBlock(Block):
    """Field behavior: Stop leaves header zero and a buffered tail until Start."""

    def __init__(self, name):
        super().__init__(name)
        self.writer = None
        self.number = 0
        self.started_paths = []
        self.Trigger.Start, self.Trigger.Stop = self.begin, self.pause

    def finish(self):
        if self.writer:
            import struct
            tail = struct.pack("<4sHHIIQ", b"LOBJ", 16, 1, 24, 9999, self.number)
            content = FILE_HEADER.pack(b"LOGG", 144, *([0] * 8), 168, 168, 1, 0, *([0] * 16)).ljust(144, b"\0") + tail
            self.writer.seek(0)
            self.writer.write(content)
            self.writer.flush()
            self.writer.close()
            self.writer = None

    def begin(self):
        self.finish()
        self.number += 1
        self.Trigger.starts += 1
        self.Trigger.Active = True
        self.started_paths.append(self.FullName)
        self.writer = Path(self.FullName).open("w+b")
        pending = FILE_HEADER.pack(b"LOGG", 144, *([0] * 8), 0, 144, 0, 0, *([0] * 16)).ljust(144, b"\0")
        self.writer.write(pending)
        self.writer.flush()

    def pause(self):
        self.Trigger.stops += 1
        self.Trigger.Active = False


def test_real_runtime_can_zipy_three_segments_publish_with_buffered_tail(fixture):
    import struct

    from vil_logging.contracts.commands import Command, CommandResult
    from vil_logging.contracts.models import Role, SessionPhase
    from vil_logging.runtime import Runtime

    capture, app, params, root = fixture
    app.blocks[0] = block = NextTriggerFinalizesBlock(str(root / "original.blf"))
    capture.connect(params)
    app.Measurement.Running = True
    paths = {}

    class Tools:
        def request(self, roles, action, session_id, **kwargs):
            results = {}
            for role in roles:
                p = kwargs.get("role_params", {}).get(role, kwargs.get("params", {}))
                if role == Role.CAN:
                    if action in {"connect", "prepare"}:
                        details = getattr(capture, action)(p)
                    elif action in {"configure", "start"}:
                        details = getattr(capture, action)(session_id, p)
                    elif action == "inspect":
                        details = capture.inspect_file(session_id)
                    elif action == "restore":
                        details = capture.restore_output(session_id)
                    else:
                        details = capture.stop(session_id)
                else:
                    details = {}
                    if action == "start":
                        paths[role] = Path(p["temp_path"])
                        paths[role].write_bytes(struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1))
                    elif action == "inspect":
                        info = paths[role].stat()
                        details = {"actual_format": "pcap", "packet_count": 0, "bytes": info.st_size,
                                   "inode": info.st_ino, "mtime_ns": info.st_mtime_ns}
                state = {"connect": "ready", "prepare": "ready", "configure": "configured", "start": "recording",
                         "stop": "stopped", "restore": "stopped", "inspect": "verified"}[action]
                results[role] = CommandResult(Command(action, role, session_id), True, state, details=details)
            return results

        def close(self, **kwargs):
            pass

        def drain_packets(self):
            return []

    runtime = Runtime(root / "profile")
    try:
        runtime.initialize().result(timeout=5)
        runtime._pool.close(abnormal=True)
        runtime._pool = Tools()
        runtime.save_preferences({"can_cfg": params["cfg_path"], "can_logging_block": "1"}).result(timeout=5)
        for number in range(3):
            runtime.toggle((Role.CAN, Role.ETHERNET)).result(timeout=5)
            assert runtime.phase == SessionPhase.RECORDING
            runtime.toggle((Role.CAN, Role.ETHERNET)).result(timeout=5)
            assert runtime.phase == SessionPhase.COMPLETED
            assert all(file.final_path.is_file() for file in runtime._plan.files)
            can_file = next(file for file in runtime._plan.files if file.role == Role.CAN)
            assert not can_file.temp_path.exists()
            assert can_file.final_path.read_bytes()[-8:] == (2 * number + 1).to_bytes(8, "little")
            assert app.Measurement.Running and not block.Trigger.Active
        assert runtime._settings.next_index == 4
        block.finish()
        runtime._submit(runtime._cleanup_retained_blf_sources).result(timeout=5)
        assert not (runtime.data_dir / "captures/.vil_work").exists()
        history = runtime._submit(lambda: runtime._repo.captures()).result(timeout=5)
        assert len(history) == 3 and all(row["phase"] == "completed" for row in history)
        assert all(file["metadata"]["inspection"]["finalization_files"][0]["cleaned"]
                   for row in history for file in row["files"] if file["role"] == "can")
    finally:
        block.finish()
        runtime.close_for_test()


def test_next_trigger_finalizes_every_real_file_without_stopping_measurement(fixture):
    from vil_logging.contracts.models import CaptureFilePlan, Role
    from vil_logging.storage.blf_snapshot import cleanup_finalization_files
    from vil_logging.storage.capture_files import cleanup_work_directory, publish_capture

    capture, app, params, root = fixture
    app.blocks[0] = block = NextTriggerFinalizesBlock(str(root / "user original.blf"))
    app.fresh_proxies = True
    block.FileNameOptions.IncrementAfterTrigger = True
    saved = []
    try:
        capture.connect(params)
        app.Measurement.Running = True
        for number in range(3):
            capture.prepare(params)
            directory = root / ".vil_work" / str(number)
            directory.mkdir(parents=True)
            path = directory / f"real_{number}.blf"
            file = CaptureFilePlan(Role.CAN, path.name, path, root / path.name)
            capture.configure(str(number), {"temp_path": str(path)})
            capture.start(str(number), {"temp_path": str(path)})
            with path.open("rb") as reader:
                assert FILE_HEADER.unpack(reader.read(FILE_HEADER.size))[10] == 0
            stopped = capture.stop(str(number))
            checked = capture.inspect_file(str(number))
            assert stopped["stop_confirmed"] and stopped["finalization_files"][0]["stopped"]
            assert checked["object_count"] == 1 and checked["bytes"] == 168
            assert not checked.get("blf_snapshot_path")  # Native closure, including buffered tail.
            publish_capture(file, checked)
            assert file.final_path.read_bytes()[-8:] == (2 * number + 1).to_bytes(8, "little")
            assert block.FullName == str(root / "user original.blf")
            assert block.FileNameOptions.IncrementAfterTrigger and app.Measurement.Running
            assert not block.Trigger.Active
            saved.append((file, checked))
        assert block.Trigger.starts == block.Trigger.stops == 6  # Three user + three disposable segments.
        for file, checked in saved:
            checked["finalization_files"] = cleanup_finalization_files(file, checked)
        assert not saved[-1][1]["finalization_files"][0].get("cleaned")  # Still owned by CANoe.
        block.finish()
        for file, checked in saved:
            assert all(row["cleaned"] for row in cleanup_finalization_files(file, checked))
            cleanup_work_directory(file.temp_path.parent)
        assert not (root / ".vil_work").exists()
        assert Path(params["cfg_path"]).read_bytes() == b"original configuration, never saved by AutoLog"
    finally:
        block.finish()


@pytest.mark.parametrize("fault", ["start_after_apply", "stop_once", "foreign_output"])
def test_finalization_faults_keep_evidence_and_never_stop_foreign_output(fixture, monkeypatch, fault):
    capture, app, params, root = fixture
    app.blocks[0] = block = NextTriggerFinalizesBlock(str(root / "manual.blf"))
    capture.connect(params)
    app.Measurement.Running = True
    capture.prepare(params)
    path = root / "record.blf"
    capture.configure("s1", {"temp_path": str(path)})
    capture.start("s1", {"temp_path": str(path)})
    begin, pause = block.begin, block.pause
    injected = []

    def start():
        begin()
        if fault == "foreign_output":
            block.FullName = str(root / "foreign.blf")
        if fault == "start_after_apply":
            raise RuntimeError("injected helper start acknowledgement failure")

    def stop():
        if fault == "stop_once" and block.Trigger.stops == 1 and not injected:
            injected.append(True)
            raise RuntimeError("injected helper stop failure")
        pause()

    monkeypatch.setattr(block.Trigger, "Start", start)
    monkeypatch.setattr(block.Trigger, "Stop", stop)
    try:
        with pytest.raises(RuntimeError):
            capture.stop("s1")
        assert not capture.stop_confirmed and path.is_file() and app.Measurement.Running
        if fault == "foreign_output":
            assert block.Trigger.Active and block.Trigger.stops == 1
            with pytest.raises(RuntimeError):
                capture.stop("s1")
            assert block.Trigger.stops == 1  # No Stop for a foreign path, even during retries.
        else:
            assert capture.stop("s1")["stop_confirmed"]
            assert capture.inspect_file("s1")["object_count"] == 1
            assert not block.Trigger.Active
    finally:
        block.finish()


def test_stop_releases_idle_output_before_waiting_for_closed_file_and_can_repeat(fixture, monkeypatch):
    capture, app, params, root = fixture
    app.blocks[0] = block = RetainedWriterBlock(str(root / "manual.blf"))
    block.FileNameOptions.IncrementAfterTrigger = True
    app.fresh_proxies = True
    capture.connect(params)
    app.Measurement.Running = True
    clock = SimpleNamespace(now=0.)
    monkeypatch.setattr("vil_logging.adapters.canoe.time", SimpleNamespace(
        monotonic=lambda: clock.now, sleep=lambda delay: setattr(clock, "now", clock.now + delay)))
    try:
        for number in range(3):
            capture.prepare(params)
            path, session = root / f"held_{number}.blf", f"held-{number}"
            capture.configure(session, {"temp_path": str(path)})
            capture.start(session, {"temp_path": str(path)})
            result = capture.stop(session)
            assert result["stop_confirmed"] and not result["output_restore_pending"]
            assert capture.inspect_file(session)["actual_format"] == "blf"
            assert block.writer is None and block.FullName == str(root / "manual.blf")
            assert block.FileNameOptions.IncrementAfterTrigger and app.Measurement.Running
        assert block.Trigger.starts == block.Trigger.stops == 3
        assert clock.now < 1  # No 28-second wait for a handle released by the filename change.
    finally:
        if block.writer is not None:
            block.writer.close()


@pytest.mark.parametrize("restart_manual", [False, True])
def test_retained_handle_does_not_block_stopped_complete_blf_and_manual_restart_is_preserved(fixture, monkeypatch, restart_manual):
    capture, app, path = prepared(fixture)
    capture.start("s1", {"temp_path": str(path)})
    clock = SimpleNamespace(now=0.)
    monkeypatch.setattr("vil_logging.adapters.canoe.time", SimpleNamespace(
        monotonic=lambda: clock.now, sleep=lambda delay: setattr(clock, "now", clock.now + delay)))
    with path.open("rb"):
        result = capture.stop("s1")
        assert result["stop_confirmed"] and not result["file_exclusive"]
        assert clock.now < 1
        checked = capture.inspect_file("s1")
        assert checked["actual_format"] == "blf" and checked["blf_snapshot_path"]
    assert capture.trigger_stopped and capture.stop_confirmed
    assert not capture.stats()["output_restore_pending"]
    assert app.blocks[0].FullName == "original_0.blf"
    assert app.blocks[0].Trigger.stops == 1
    if restart_manual:
        app.blocks[0].Trigger.Active = True
        with pytest.raises(RuntimeError, match="restarted"):
            capture.inspect_file("s1")
        assert app.blocks[0].Trigger.stops == 1 and app.blocks[0].Trigger.Active
        app.blocks[0].Trigger.Active = False
    capture.stop("s1")
    assert capture.stop_confirmed and app.blocks[0].Trigger.stops == 1
    assert capture.inspect_file("s1")["actual_format"] == "blf"


def test_idle_cfg_switch_reuses_owned_window_and_preserves_unsaved_edits(fixture):
    capture, app, params, root = fixture
    capture.connect(params)
    other = root / "other.cfg"
    other.write_bytes(b"other original")
    app.Configuration.Modified = True
    with pytest.raises(RuntimeError, match="unsaved"):
        capture.connect({"cfg_path": str(other)})
    assert app.Configuration.FullName == params["cfg_path"]
    app.Configuration.Modified = False
    capture.connect({"cfg_path": str(other)})
    assert capture.app is app
    assert len(app.open_calls) == 2 and app.Configuration.FullName == str(other)
    assert other.read_bytes() == b"other original"


def test_manual_cfg_change_requires_explicit_matching_selection(fixture):
    capture, app, params, root = fixture
    capture.connect(params)
    other = root / "manual.cfg"
    other.write_bytes(b"original")
    app.Configuration.FullName = str(other)
    with pytest.raises(RuntimeError, match="owned CANoe window changed"):
        capture.connect(params)
    capture.connect({"cfg_path": str(other)})
    assert capture.app is app and len(app.open_calls) == 1


def test_single_client_mode_opens_unconfigured_object_without_accepting_existing_projects(tmp_path, monkeypatch):
    import pywintypes

    from vil_logging.diagnostics import canoe_setup

    class UnconfiguredApplication(Application):
        FullName = "C:/registered/CANoe64.exe"

        @property
        def Configuration(self):
            if not self.open_calls:
                raise pywintypes.com_error(-2147352567, "no configuration", (0, None, None, None, 0, -2147467259), None)
            return self._configuration

        @Configuration.setter
        def Configuration(self, value):
            self._configuration = value

    ini = tmp_path / "can.ini"
    ini.write_bytes(b"SingleCOMClient=1\r\n")
    monkeypatch.setattr(canoe_setup, "registered_settings_file", lambda exe: ini)
    captures = []
    for name in ["can", "diag"]:
        cfg = tmp_path / f"{name}.cfg"
        cfg.write_bytes(b"original")
        app = UnconfiguredApplication()
        capture = CanoeCapture(create_application=lambda: app)
        capture.connect({"cfg_path": str(cfg)})
        captures.append(capture)
    assert captures[0].app is not captures[1].app
    assert captures[0].app.Configuration.FullName.endswith("can.cfg")
    assert captures[1].app.Configuration.FullName.endswith("diag.cfg")
    assert all(any(row["event"] == "canoe.unconfigured_single_client" for row in c.journal) for c in captures)


def test_external_logging_stop_is_detected_and_closed_file_can_still_be_retained(fixture):
    capture, app, path = prepared(fixture)
    capture.start("s1", {"temp_path": str(path)})
    app.blocks[0].Trigger.Stop()  # Simulate the existing CAPL panel, outside AutoLog.
    state, details = capture.query()
    assert state == "error" and not details["trigger_active"]
    capture.stop("s1")
    assert app.blocks[0].Trigger.stops == 1  # AutoLog does not issue a second stop.
    assert capture.inspect_file("s1")["actual_format"] == "blf"
    assert app.Measurement.Running
