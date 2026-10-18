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
        self.FullName = name
        self.Trigger = Trigger(self)
        self.FileNameOptions = SimpleNamespace(IncrementAfterTrigger=False, IncrementAfterGrowth=False,
                                               IncrementAfterDuration=False)


class Application:
    def __init__(self, count=1):
        self.blocks = [Block(f"original_{i}.blf") for i in range(count)]
        self.Configuration = SimpleNamespace(FullName="", OnlineSetup=SimpleNamespace(
            LoggingCollection=SimpleNamespace(Count=count, Item=lambda index: self.blocks[index - 1])))
        self.Measurement = SimpleNamespace(Running=False)
        self.open_calls = []

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


def test_existing_configuration_is_never_replaced(fixture):
    capture, app, params, _ = fixture
    app.Configuration.FullName = "C:/unrelated.cfg"
    with pytest.raises(RuntimeError, match="existing configuration"):
        capture.connect(params)
    assert not app.open_calls


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


@pytest.mark.parametrize("fault", ["configuration", "block", "filename", "measurement", "splitting"])
def test_external_changes_prevent_start(fixture, fault):
    capture, app, path = prepared(fixture)
    block = app.blocks[0]
    if fault == "configuration":
        app.Configuration.FullName = "C:/another.cfg"
    elif fault == "block":
        app.blocks[0] = Block("other.blf")
    elif fault == "filename":
        block.FullName = "other.blf"
    elif fault == "measurement":
        app.Measurement.Running = False
    else:
        block.FileNameOptions.IncrementAfterTrigger = True
    with pytest.raises(RuntimeError):
        capture.start("s1", {"temp_path": str(path)})
    assert block.Trigger.starts == 0


def test_no_measurement_or_existing_recording_or_splitting_blocks_preparation(fixture):
    capture, app, params, _ = fixture
    with pytest.raises(RuntimeError, match="Start measurement"):
        capture.prepare(params)
    app.Measurement.Running = True
    app.blocks[0].Trigger.Active = True
    with pytest.raises(RuntimeError, match="already recording"):
        capture.prepare(params)
    app.blocks[0].Trigger.Active = False
    app.blocks[0].FileNameOptions.IncrementAfterGrowth = True
    with pytest.raises(RuntimeError, match="splitting"):
        capture.prepare(params)


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
