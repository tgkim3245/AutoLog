"""User choices, asynchronous save acknowledgements and readable readiness results."""

from dataclasses import replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QFileDialog

from vil_logging.contracts.models import AppSettings, ConnectionState, Role, TargetSnapshot
from vil_logging.ui.environment_dialog import EnvironmentDialog
from vil_logging.ui.settings_dialog import SettingsDialog


@pytest.fixture
def dialog(qtbot):
    instance = SettingsDialog()
    qtbot.addWidget(instance)
    instance.set_settings(AppSettings(output_dir="C:/captures", version=4))
    return instance


def discovered():
    return {
        "tshark": {"status": "ready", "path": "C:/Wireshark/tshark.exe", "version": "TShark test"},
        "interfaces": [{"id": r"\Device\NPF_{TEST}", "name": "차량 이더넷",
                        "description": "USB Ethernet", "status": "up", "capture_available": True}],
        "selected_nic_id": "", "npcap": {"status": "present"},
    }


@pytest.mark.parametrize("key,kind,selected", [
    ("can_cfg", "cfg", "C:/test/car.cfg"),
    ("diag_cfg", "cfg", "C:/test/diag.cfg"),
    ("tshark_path", "tool", "C:/Wireshark/tshark.exe"),
    ("output_dir", "folder", "D:/captures"),
])
def test_picker_immediately_requests_persistence(dialog, monkeypatch, key, kind, selected):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (selected, ""))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: selected)
    spy = QSignalSpy(dialog.preferences_changed)
    dialog._browse(key, kind)
    assert spy.count() == 1
    assert spy.at(0)[0] == {key: selected}
    assert dialog.feedback.property("tone") == "checking"
    dialog.set_settings(replace(dialog._settings, **{key: selected}, version=5))
    assert dialog.feedback.property("tone") == "ready"


def test_older_save_acknowledgement_never_overwrites_newer_path(dialog):
    original = dialog._settings
    dialog.fields["can_cfg"].setText("C:/first.cfg")
    dialog._save_preferences(("can_cfg",))
    dialog.fields["can_cfg"].setText("C:/second.cfg")
    dialog._save_preferences(("can_cfg",))
    dialog.set_settings(replace(original, can_cfg="C:/first.cfg", version=5))
    assert dialog.fields["can_cfg"].text() == "C:/second.cfg"
    assert dialog.feedback.property("tone") == "checking"
    dialog.set_settings(replace(original, can_cfg="C:/second.cfg", version=6))
    assert not dialog._pending_patches
    assert dialog.feedback.property("tone") == "ready"


def test_noop_save_with_same_version_finishes_saving_indicator(dialog):
    dialog._save_preferences(("output_dir",), force=True)
    dialog.set_settings(dialog._settings)
    assert not dialog._pending_patches
    assert dialog.feedback.property("tone") == "ready"


def test_network_shows_friendly_name_and_saves_identifier_without_manual_typing(dialog):
    dialog.set_settings(replace(dialog._settings, tshark_path="C:/Wireshark/tshark.exe"))
    dialog.set_connection_discovery(discovered())
    spy = QSignalSpy(dialog.preferences_changed)
    assert "차량 이더넷" in dialog.nic_input.itemText(1)
    assert "NPF" not in dialog.nic_input.itemText(1)
    dialog.nic_input.setCurrentIndex(1)
    assert spy.at(0)[0] == {"nic_id": r"\Device\NPF_{TEST}"}
    dialog.set_settings(replace(dialog._settings, nic_id=r"\Device\NPF_{TEST}", version=5))
    dialog.set_language("en")
    assert dialog.nic_input.currentData() == r"\Device\NPF_{TEST}"
    assert "Connected" in dialog.nic_input.currentText()
    dialog.nic_input.setCurrentIndex(0)
    dialog.set_language("ko")
    assert dialog.nic_input.currentData() == ""  # Keep an explicitly cleared choice until saved.


def test_missing_previous_network_is_preserved_instead_of_selecting_first(dialog):
    dialog.set_settings(replace(dialog._settings, nic_id="missing-adapter"))
    dialog.set_connection_discovery(discovered())
    assert dialog.nic_input.currentData() == "missing-adapter"
    assert "찾을 수 없음" in dialog.nic_input.currentText()


def test_prepare_immediately_shows_progress_and_then_actionable_result(dialog):
    requested = QSignalSpy(dialog.prepare_requested)
    saved = QSignalSpy(dialog.preferences_changed)
    dialog.fields["can_cfg"].setText("C:/selected.cfg")
    dialog._prepare(Role.CAN)
    assert requested.count() == 1 and requested.at(0)[0] == Role.CAN
    assert saved.at(0)[0]["can_cfg"] == "C:/selected.cfg"
    assert not dialog.prepare_buttons[Role.CAN].isEnabled()
    assert "확인 중" in dialog.target_labels[Role.CAN].text()
    dialog.set_preparation_report({"role": "can", "status": "error", "message_ko": "구성 파일이 없습니다.",
        "message_en": "Configuration missing.", "detail": "C:/selected.cfg"})
    assert dialog.prepare_buttons[Role.CAN].isEnabled()
    assert "구성 파일이 없습니다" in dialog.target_labels[Role.CAN].text()
    assert "다시 선택" in dialog.next_actions[Role.CAN].text()
    assert "selected.cfg" in dialog.result_details[Role.CAN].text()
    dialog.set_language("en")
    assert "Configuration missing" in dialog.target_labels[Role.CAN].text()


def test_inventory_refresh_never_requests_automatic_tool_replacement(dialog):
    spy = QSignalSpy(dialog.discovery_requested)
    dialog._request_discovery()
    assert spy.count() == 1
    dialog.set_discovery_busy(False)
    dialog._request_discovery()
    assert spy.count() == 2
    assert not hasattr(dialog, "find_button")


def test_discovery_never_overwrites_a_tool_selected_while_scan_was_running(dialog):
    dialog._request_discovery()
    dialog.fields["tshark_path"].setText("D:/chosen/tshark.exe")
    dialog.set_connection_discovery(discovered())
    assert dialog.fields["tshark_path"].text() == "D:/chosen/tshark.exe"


def test_environment_is_readable_and_details_are_optional(qtbot):
    instance = EnvironmentDialog()
    qtbot.addWidget(instance)
    instance.set_report({}, discovered())
    assert instance.details.isHidden()
    assert "Wireshark" in instance.cards["tshark"][2].text()
    assert "설치" in instance.cards["canoe"][2].text()
    spy = QSignalSpy(instance.settings_requested)
    instance.cards["network"][3].click()
    assert spy.at(0)[0] == "ethernet"
    instance.set_busy(True)
    assert not instance.refresh_button.isEnabled()
    assert "확인 중" in instance.summary.text()
    instance.set_error("A diagnostic error")
    assert instance.refresh_button.isEnabled()
    assert instance.summary.property("tone") == "error"
    instance.set_language("en")
    assert instance.summary.text() == "Check failed"


def test_opening_settings_refreshes_network_inventory(dialog):
    dialog.set_connection_discovery(discovered())
    spy = QSignalSpy(dialog.discovery_requested)
    dialog.show()
    assert spy.count() == 1
    assert dialog._discovering
    assert not dialog.nic_input._timer.isActive()  # Storage tab does not poll counters.


def test_discovery_timeout_keeps_manual_path_selection_available(dialog, qtbot):
    dialog._discovery_timer.setInterval(20)
    dialog._request_discovery()
    qtbot.waitUntil(lambda: not dialog._discovering, timeout=2000)
    assert dialog.fields["tshark_path"].isEnabled()
    assert "다시 열어" in dialog.tool_status.text()
    assert dialog.tool_status.property("tone") == "error"
    dialog._request_discovery()
    dialog.set_discovery_error("A failed query")
    assert dialog.fields["tshark_path"].isEnabled()
    assert dialog.tool_status.text() == "A failed query"
    dialog.set_connection_discovery(discovered())
    assert dialog.tool_status.property("tone") == "ready"


def test_missing_driver_keeps_network_choices_and_refers_to_separate_guide(dialog):
    report = discovered()
    report["npcap"] = {"status": "missing"}
    report["interfaces"][0]["capture_available"] = False
    dialog.set_connection_discovery(report)
    assert dialog.nic_input.count() == 2
    assert "차량 이더넷" in dialog.nic_input.itemText(1)
    assert not hasattr(dialog, "npcap_button")
    assert "설치" in dialog.driver_status.text()
    report["npcap"] = {"status": "present"}
    dialog.set_connection_discovery(report)
    assert "필요" not in dialog.driver_status.text()


def test_unknown_readiness_does_not_become_a_false_connection_error(dialog):
    dialog.set_target(TargetSnapshot(Role.ETHERNET, connection=ConnectionState.UNKNOWN))
    assert dialog.target_labels[Role.ETHERNET].property("tone") == "attention"


def test_settings_identify_running_version(dialog):
    from vil_logging import __version__
    assert __version__ in dialog.windowTitle()
    assert __version__ in dialog.version_label.text()


def test_canoe_block_choices_are_explicit_persisted_and_cleared_for_new_cfg(dialog):
    dialog.set_preparation_report({"role": "can", "status": "attention", "blocks": [
        {"id": "1", "name": "first.blf"}, {"id": "2", "name": "second.blf"}], "selected_block": ""})
    combo = dialog.block_inputs["can_logging_block"]
    assert combo.currentData() == ""
    spy = QSignalSpy(dialog.preferences_changed)
    combo.setCurrentIndex(2)
    assert spy.at(0)[0] == {"can_logging_block": "2"}
    dialog.set_settings(replace(dialog._settings, can_logging_block="2", version=5))
    assert combo.currentData() == "2"
    dialog.fields["can_cfg"].setText("C:/another.cfg")
    assert combo.currentData() == "" and combo.count() == 1


def test_canoe_choices_show_name_format_and_path_and_disable_non_blf(dialog):
    dialog.set_preparation_report({"role": "can", "status": "attention", "blocks": [
        {"id": "1", "name": "CAN_Logging", "format": "blf", "path": "C:/can.blf", "compatible": True},
        {"id": "2", "name": "ETH_Logging", "format": "pcapng", "path": "C:/eth.pcapng", "compatible": False}],
        "selected_block": "1"})
    combo = dialog.block_inputs["can_logging_block"]
    assert "CAN_Logging" in combo.currentText() and ".blf" in combo.currentText()
    assert combo.itemData(1, Qt.ItemDataRole.ToolTipRole) == "C:/can.blf"
    assert not combo.model().item(2).isEnabled()
