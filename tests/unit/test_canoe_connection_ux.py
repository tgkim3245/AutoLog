from dataclasses import replace

import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QPushButton

from vil_logging.adapters.canoe import CanoeCapture, _create_application
from vil_logging.contracts.models import AppSettings, Role
from vil_logging.diagnostics import canoe_setup
from vil_logging.ui.settings_dialog import SettingsDialog


@pytest.mark.parametrize("enabled,processes,blocked", [(False, [123], True), (False, [], False), (True, [123], False)])
def test_connection_automatically_prepares_independence_before_creating_com(tmp_path, monkeypatch, enabled, processes, blocked):
    import win32com.client

    path = tmp_path / "can.ini"
    path.write_bytes(b"SingleCOMClient=" + (b"1" if enabled else b"0") + b"\r\n")
    monkeypatch.setattr(canoe_setup, "registered_settings_file", lambda: path)
    monkeypatch.setattr(canoe_setup, "canoe_process_ids", lambda: processes)
    created = []
    marker = object()
    def dispatch(name):
        assert canoe_setup.single_client_enabled(path)
        created.append(name)
        processes.append(456)
        return marker
    monkeypatch.setattr(win32com.client, "DispatchEx", dispatch)
    if blocked:
        with pytest.raises(canoe_setup.CanoeActivationError) as failure:
            _create_application()
        assert failure.value.connection_issue == "restart_required"
        assert not created
    else:
        result = _create_application()
        assert result.application is marker and result.process_id == 456
        assert created == ["CANoe.Application"]
    assert path.read_bytes() == b"SingleCOMClient=" + (b"0" if blocked else b"1") + b"\r\n"


def test_two_cfg_connections_get_new_processes_without_a_user_mode_choice(tmp_path, monkeypatch):
    import win32com.client

    path = tmp_path / "can.ini"
    original = b"SingleCOMClient=0\r\n"
    path.write_bytes(original)
    processes = []
    monkeypatch.setattr(canoe_setup, "registered_settings_file", lambda: path)
    monkeypatch.setattr(canoe_setup, "canoe_process_ids", lambda: list(processes))

    def dispatch(_name):
        processes.append(100 + len(processes))
        return object()
    monkeypatch.setattr(win32com.client, "DispatchEx", dispatch)
    can = _create_application()
    diag = _create_application()
    assert can.application is not diag.application
    assert (can.process_id, diag.process_id) == (100, 101)
    assert can.setup["changed"] and not diag.setup["changed"]
    assert list(path.parent.glob("*.bak"))[0].read_bytes() == original


@pytest.mark.parametrize("new_processes", [[], [456, 789]])
def test_activation_rejects_reused_or_ambiguous_processes(tmp_path, monkeypatch, new_processes):
    import win32com.client

    path = tmp_path / "can.ini"
    path.write_bytes(b"SingleCOMClient=1\r\n")
    processes = [123]
    monkeypatch.setattr(canoe_setup, "registered_settings_file", lambda: path)
    monkeypatch.setattr(canoe_setup, "canoe_process_ids", lambda: list(processes))
    monkeypatch.setattr(win32com.client, "DispatchEx", lambda name: processes.extend(new_processes) or object())
    with pytest.raises(canoe_setup.CanoeActivationError) as failure:
        _create_application()
    assert failure.value.connection_issue == "restart_required"


def test_blocked_activation_reports_actionable_journal_without_opening_com(tmp_path, monkeypatch):
    path = tmp_path / "can.cfg"
    path.write_bytes(b"original")

    def blocked():
        raise canoe_setup.CanoeActivationError("restart_required", "Close CANoe once", path="can.ini", process_ids=[123])

    monkeypatch.setattr(canoe_setup, "ensure_independent_activation", blocked)
    capture = CanoeCapture()
    with pytest.raises(canoe_setup.CanoeActivationError):
        capture.connect({"cfg_path": str(path)})
    assert capture.app is None and capture.block is None
    assert capture.journal[-1]["event"] == "canoe.activation_failed"
    assert path.read_bytes() == b"original"


def test_unreadable_setup_never_falls_back_to_a_shared_com_instance(monkeypatch):
    import win32com.client

    def missing():
        raise FileNotFoundError("Generated missing settings")
    monkeypatch.setattr(canoe_setup, "registered_settings_file", missing)
    created = []
    monkeypatch.setattr(win32com.client, "DispatchEx", lambda name: created.append(name))
    with pytest.raises(canoe_setup.CanoeActivationError) as failure:
        _create_application()
    assert failure.value.connection_issue == "setup_failed"
    assert not created


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


def test_restart_guidance_has_no_connection_mode_option_and_keeps_diagnostics(qtbot):
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.set_preparation_report({"role": "diag", "status": "attention", "connection_issue": "restart_required",
        "detail": "CANoe 작업을 저장하고 닫으세요.", "diagnostic_detail": "Traceback: generated details"})
    assert dialog.findChild(QPushButton, "canoeSetupButton") is None
    assert dialog.findChild(QPushButton, "setupDiagConnectionButton") is None
    assert "Traceback" not in dialog.result_details[Role.DIAG].text()
    assert "Traceback" in dialog.result_details[Role.DIAG].toolTip()


def test_each_card_shows_its_own_connected_cfg_and_process(qtbot):
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    for role, cfg, pid in ((Role.CAN, "C:/CAN.cfg", 123), (Role.DIAG, "C:/Diag.cfg", 456)):
        dialog.set_preparation_report({"role": role.value, "status": "attention", "connected_cfg": cfg, "canoe_pid": pid,
                                       "detail_ko": "연결된 구성", "detail_en": "Independent configuration connected"})
    assert "CAN.cfg" in dialog.connection_summaries[Role.CAN].text()
    assert "123" in dialog.connection_summaries[Role.CAN].text()
    assert "Diag.cfg" in dialog.connection_summaries[Role.DIAG].text()
    assert "456" in dialog.connection_summaries[Role.DIAG].text()
    dialog.set_language("en")
    assert "Connected configuration" in dialog.connection_summaries[Role.CAN].text()
    assert dialog.result_details[Role.CAN].text() == "Independent configuration connected"
    assert dialog.connection_summaries[Role.DIAG].toolTip() == "C:/Diag.cfg"
