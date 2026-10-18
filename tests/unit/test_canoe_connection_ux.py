from dataclasses import replace

import pytest
from PySide6.QtTest import QSignalSpy

from vil_logging.adapters.canoe import CanoeCapture, _create_application
from vil_logging.contracts.models import AppSettings, Role
from vil_logging.diagnostics import canoe_setup
from vil_logging.ui import canoe_setup_dialog
from vil_logging.ui.settings_dialog import SettingsDialog


@pytest.mark.parametrize("enabled,processes,blocked", [(False, [123], True), (False, [], False), (True, [123, 456], False)])
def test_default_mode_never_activates_existing_window_before_com(tmp_path, monkeypatch, enabled, processes, blocked):
    import win32com.client

    path = tmp_path / "can.ini"
    path.write_bytes(b"SingleCOMClient=" + (b"1" if enabled else b"0") + b"\r\n")
    monkeypatch.setattr(canoe_setup, "registered_settings_file", lambda: path)
    monkeypatch.setattr(canoe_setup, "canoe_process_ids", lambda: processes)
    created = []
    marker = object()
    monkeypatch.setattr(win32com.client, "DispatchEx", lambda name: created.append(name) or marker)
    if blocked:
        with pytest.raises(canoe_setup.IndependentConnectionsRequired):
            _create_application()
        assert not created
    else:
        assert _create_application() is marker
        assert created == ["CANoe.Application"]
    assert path.read_bytes() == b"SingleCOMClient=" + (b"1" if enabled else b"0") + b"\r\n"


def test_blocked_activation_reports_actionable_journal_without_opening_com(tmp_path, monkeypatch):
    path = tmp_path / "can.cfg"
    path.write_bytes(b"original")

    def blocked():
        raise canoe_setup.IndependentConnectionsRequired("can.ini", [123])

    monkeypatch.setattr(canoe_setup, "check_activation", blocked)
    capture = CanoeCapture()
    with pytest.raises(canoe_setup.IndependentConnectionsRequired):
        capture.connect({"cfg_path": str(path)})
    assert capture.app is None and capture.block is None
    assert capture.journal[-1]["event"] == "canoe.independent_setup_required"
    assert path.read_bytes() == b"original"


def test_unknown_setting_retains_existing_configuration_identity_protection(monkeypatch):
    def missing():
        raise FileNotFoundError("Generated missing settings")
    monkeypatch.setattr(canoe_setup, "registered_settings_file", missing)
    assert canoe_setup.check_activation() is None


def test_can_then_diag_does_not_resend_old_block_before_settings_ack(qtbot):
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    original = AppSettings(can_cfg="C:/CAN.cfg", diag_cfg="C:/Diag.cfg", version=4)
    dialog.set_settings(original)
    saved = QSignalSpy(dialog.preferences_changed)
    requested = QSignalSpy(dialog.prepare_requested)
    dialog._prepare(Role.CAN)
    # The backend auto-selected CAN block 1; its settings ACK is still queued.
    dialog._prepare(Role.DIAG)
    assert saved.count() == 0
    assert requested.count() == 2 and requested.at(1)[0] == Role.DIAG
    dialog.set_settings(replace(original, can_logging_block="1", version=5))
    assert dialog.block_inputs["can_logging_block"].currentData() == "1"
    assert not dialog._pending_patches


def test_preparation_flushes_only_real_edits(qtbot):
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    saved = QSignalSpy(dialog.preferences_changed)
    dialog.fields["diag_cfg"].setText("C:/new.cfg")
    dialog._prepare(Role.DIAG)
    assert saved.count() == 1
    assert saved.at(0)[0] == {"diag_cfg": "C:/new.cfg", "diag_logging_block": ""}


def test_second_connection_never_replays_a_dirty_value_already_waiting_for_ack(qtbot):
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.set_settings(AppSettings(can_cfg="C:/old.cfg", diag_cfg="C:/diag.cfg", version=4))
    dialog.fields["can_cfg"].setText("C:/new.cfg")
    saved = QSignalSpy(dialog.preferences_changed)
    requested = QSignalSpy(dialog.prepare_requested)
    dialog._prepare(Role.CAN)
    assert saved.count() == 1
    assert saved.at(0)[0] == {"can_cfg": "C:/new.cfg", "can_logging_block": ""}
    # Backend may now have selected block 1 while both save/result ACKs wait for the UI.
    dialog._prepare(Role.DIAG)
    assert requested.count() == 2 and saved.count() == 1


def test_setup_action_is_visible_and_original_error_stays_in_tooltip(qtbot):
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.set_preparation_report({"role": "diag", "status": "attention", "action": "canoe_setup",
        "detail": "CANoe 작업을 저장하고 닫으세요.", "diagnostic_detail": "Traceback: generated details"})
    assert not dialog.setup_actions[Role.DIAG].isHidden()
    assert "Traceback" not in dialog.result_details[Role.DIAG].text()
    assert "Traceback" in dialog.result_details[Role.DIAG].toolTip()


def test_setup_blocks_changes_until_user_closes_windows_and_refreshes(qtbot, tmp_path, monkeypatch):
    path = tmp_path / "can.ini"
    path.write_bytes(b"SingleCOMClient=0\r\n")
    processes = [123]
    monkeypatch.setattr(canoe_setup_dialog, "registered_settings_file", lambda: path)
    monkeypatch.setattr(canoe_setup_dialog, "canoe_process_ids", lambda: list(processes))
    dialog = canoe_setup_dialog.CanoeSetupDialog()
    qtbot.addWidget(dialog)
    assert not dialog.enable_button.isEnabled()
    assert "1개" in dialog.status.text()
    processes.clear()
    dialog.refresh_button.click()
    assert dialog.enable_button.isEnabled()
    assert dialog.applied_enabled is None


def test_setup_apply_retries_both_cfgs_with_current_values(qtbot, monkeypatch):
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.set_settings(AppSettings(can_cfg="C:/can.cfg", diag_cfg="C:/diag.cfg", can_logging_block="1", diag_logging_block="1"))

    class Setup:
        applied_enabled = True

        def __init__(self, *args):
            pass

        def exec(self):
            pass

    monkeypatch.setattr(canoe_setup_dialog, "CanoeSetupDialog", Setup)
    requested = QSignalSpy(dialog.prepare_requested)
    saved = QSignalSpy(dialog.preferences_changed)
    dialog._open_canoe_setup()
    assert [requested.at(i)[0] for i in range(requested.count())] == [Role.CAN, Role.DIAG]
    assert saved.count() == 0
