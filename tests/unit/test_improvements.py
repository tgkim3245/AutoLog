import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QDialog, QPushButton, QSystemTrayIcon, QVBoxLayout

from vil_logging.contracts.models import AppEvent, Role
from vil_logging.diagnostics.canoe_hardware import inspect_hardware, parse_baseline
from vil_logging.diagnostics.canoe_readiness import readiness_stage, stage_text
from vil_logging.storage.repository import Repository
from vil_logging.ui.main_window import MainWindow
from vil_logging.ui.window_fit import fit_window


def hardware_app():
    return SimpleNamespace(ChannelMappingName="CANoe", Configuration=SimpleNamespace(
        GeneralSetup=SimpleNamespace(Channels=lambda bus: 2),
        DistributedMode=SimpleNamespace(RTServer="", Connected=0)))


@pytest.fixture
def product_fonts(qapp):
    # The Windows offscreen plugin does not discover system fonts automatically.
    # Measure the same fonts/style as the native app, rather than missing-glyph boxes.
    font, style = qapp.font(), qapp.style().objectName()
    ids = []
    for filename in ("malgun.ttf", "malgunbd.ttf", "segoeui.ttf", "msyh.ttc"):
        path = Path("C:/Windows/Fonts") / filename
        if path.is_file():
            ids.append(QFontDatabase.addApplicationFont(str(path)))
    qapp.setFont(QFont("Malgun Gothic", 9))
    qapp.setStyle("Fusion")
    yield
    qapp.setFont(font)
    qapp.setStyle(style)
    for identifier in ids:
        QFontDatabase.removeApplicationFont(identifier)


def channels(_application, _count):
    return [{"logical": i, "hw_type": 57, "serial": 1234, "port": i,
             "name": "VN fixture", "driver_version": 1, "physical": True, "config_error": 0} for i in (1, 2)]


def test_hardware_baseline_compares_serial_and_port_and_cfg(tmp_path):
    app, cfg = hardware_app(), str(tmp_path / "can.cfg")
    report = inspect_hardware(app, cfg, query=channels)
    assert report["status"] == "unreferenced"
    baseline = json.dumps(report["baseline"])
    assert parse_baseline(baseline)["channels"][0]["serial"] == 1234
    assert inspect_hardware(app, cfg, baseline, query=channels)["status"] == "match"
    def changed(*args):
        rows = channels(*args)
        rows[1]["serial"] = 9999
        return rows
    assert inspect_hardware(app, cfg, baseline, query=changed)["status"] == "mismatch"
    assert inspect_hardware(app, cfg + ".other", baseline, query=channels)["status"] == "mismatch"


@pytest.mark.parametrize("mode", ["missing_api", "remote", "virtual", "driver_error"])
def test_hardware_unknown_is_never_verified(mode, tmp_path):
    app = hardware_app()
    query = channels
    if mode == "missing_api":
        app = SimpleNamespace()
    elif mode == "remote":
        app.Configuration.DistributedMode = SimpleNamespace(RTServer="test-target", Connected=1)
    elif mode == "virtual":
        def query(*args):
            rows = channels(*args)
            rows[0]["physical"] = False
            return rows
    else:
        def query(*args):
            raise OSError("driver missing")
    report = inspect_hardware(app, tmp_path / "can.cfg", query=query)
    assert report["status"] == "unavailable" and "baseline" not in report


@pytest.mark.parametrize("server,connected", [("", 1), ("test-target", 0), ("test-target", 1)])
def test_remote_target_never_queries_local_driver(tmp_path, server, connected):
    app = hardware_app()
    app.Configuration.DistributedMode = SimpleNamespace(RTServer=server, Connected=connected)
    def forbidden(*args):
        pytest.fail("Remote target must not use the local XL mapping")
    report = inspect_hardware(app, tmp_path / "can.cfg", query=forbidden)
    assert report["status"] == "unavailable" and "baseline" not in report
    assert report["distributed_mode"] == {"server": server, "connected": connected}


@pytest.mark.parametrize("mode", [True, None, SimpleNamespace(RTServer=None, Connected=0),
                                   SimpleNamespace(RTServer="", Connected="unknown")])
def test_unreadable_distributed_state_cannot_claim_local_mapping(tmp_path, mode):
    app = hardware_app()
    app.Configuration.DistributedMode = mode
    def forbidden(*args):
        pytest.fail("Unknown target must not use the local XL mapping")
    assert inspect_hardware(app, tmp_path / "can.cfg", query=forbidden)["status"] == "unavailable"


def test_cfg_change_clears_hardware_reference(tmp_path):
    repo = Repository(tmp_path / "state.db")
    try:
        repo.load_settings()
        baseline = json.dumps(inspect_hardware(hardware_app(), tmp_path / "a.cfg", query=channels)["baseline"])
        repo.save_preferences({"can_cfg": str(tmp_path / "a.cfg")})
        repo.save_preferences({"can_hardware_baseline": baseline})
        assert repo.load_settings().can_hardware_baseline == baseline
        stored = json.loads(repo._connection.execute("SELECT document FROM settings WHERE id=1").fetchone()[0])
        assert "can_hardware_baseline" not in stored and "diag_hardware_baseline" not in stored
        assert repo.save_preferences({"can_cfg": str(tmp_path / "b.cfg")}).can_hardware_baseline == ""
    finally:
        repo.close()


def test_corrupt_hardware_reference_cannot_report_a_match(tmp_path):
    report = inspect_hardware(hardware_app(), tmp_path / "can.cfg", "invalid json", query=channels)
    assert report["status"] == "unavailable" and report["reference_required"]
    assert "baseline" not in report


@pytest.mark.parametrize("change,stage", [({}, "segment_ready"), ({"measurement_running": False}, "measurement_waiting"),
    ({"view_only": True}, "license_required"), ({"trigger_active": True}, "block_recording"),
    ({"selected_block": ""}, "block_required"), ({"hardware": {"status": "mismatch"}}, "hardware_mismatch"),
    ({"hardware": {"status": "unavailable", "reference_required": True}}, "hardware_unavailable")])
def test_readiness_has_specific_stage_and_three_languages(change, stage):
    details = {"selected_block": "1", "measurement_running": True, **change}
    assert readiness_stage(details) == stage
    assert all(stage_text(stage, language) for language in ("ko", "en", "zh"))


def test_activity_filter_preserves_details_and_500_rows_without_copy_or_count(qtbot, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    window = MainWindow()
    qtbot.addWidget(window)
    window.add_event(AppEvent("OLD", "ERROR"))
    window.event_filter.setCurrentIndex(1)
    for index in range(499):
        window.add_event(AppEvent("INFO", params={"index": index}))
    window.add_event(AppEvent("TEST_ERROR", "ERROR", original="original traceback", params={"code": "0x123"}))
    assert len(window._events) == 500 and window.event_list.count() == 1
    assert "original traceback" in window.event_list.item(0).toolTip()
    assert window.event_list.item(0).data(Qt.ItemDataRole.UserRole).params["code"] == "0x123"
    assert not hasattr(window, "event_copy") and not hasattr(window, "event_count")
    window.set_language("zh")
    assert window.event_list.count() == 1
    window.event_filter.setCurrentIndex(0)
    assert window.event_list.count() == 500


def test_small_screen_keeps_footer_reachable(qtbot, monkeypatch, product_fonts):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(30)
    fit_window(window, QRect(0, 0, 800, 540))
    qtbot.wait(30)
    assert window.height() <= 492
    assert window.main_scroll.verticalScrollBar().maximum() > 0
    window.main_scroll.ensureWidgetVisible(window.debug_status)
    qtbot.wait(20)
    point = window.debug_status.mapTo(window.main_scroll.viewport(), window.debug_status.rect().center())
    assert window.main_scroll.viewport().rect().contains(point)
    window.set_language("en")
    window.set_preparation_report({"role": "can", "status": "attention", "readiness_stage": "measurement_waiting"})
    fit_window(window, QRect(0, 0, 400, 540))
    qtbot.wait(30)
    assert window.main_scroll.horizontalScrollBar().maximum() == 0


def test_hardware_reference_is_explicit_and_locked_while_recording(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    window = MainWindow()
    qtbot.addWidget(window)
    dialog = window.settings_dialog
    report = {"role": "can", "status": "attention", "readiness_stage": "measurement_waiting",
              "hardware": inspect_hardware(hardware_app(), tmp_path / "a.cfg", query=channels)}
    dialog.set_preparation_report(report)
    patches = []
    dialog.preferences_changed.connect(patches.append)
    assert not patches
    dialog.hardware_reference_buttons[Role.CAN].click()
    assert parse_baseline(patches[0]["can_hardware_baseline"])
    dialog.set_busy(True)
    assert not dialog.hardware_reference_buttons[Role.CAN].isEnabled()


def test_small_screen_dialog_actions_remain_reachable(qtbot):
    dialog = QDialog()
    qtbot.addWidget(dialog)
    layout = QVBoxLayout(dialog)
    for _ in range(5):
        button = QPushButton("Action")
        button.setMinimumHeight(80)
        layout.addWidget(button)
    dialog.show()
    qtbot.wait(20)
    fit_window(dialog, QRect(0, 0, 800, 360))
    qtbot.wait(20)
    assert dialog.height() <= 312
    dialog._fit_scroll.ensureWidgetVisible(button)
    qtbot.wait(20)
    point = button.mapTo(dialog._fit_scroll.viewport(), button.rect().center())
    assert dialog._fit_scroll.viewport().rect().contains(point)
