import time
from dataclasses import replace

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QSystemTrayIcon

from vil_logging.contracts.models import (
    AppSettings,
    ObservationState,
    Role,
    SessionPhase,
    TargetSnapshot,
)
from vil_logging.monitors.rules import parse_rules
from vil_logging.ui.main_window import MainWindow
from vil_logging.ui.validation_panel import ValidationPanel


def test_rule_fields_start_empty_and_partial_criteria_cannot_save(qtbot):
    dialog = ValidationPanel()
    qtbot.addWidget(dialog)
    spy = QSignalSpy(dialog.preferences_changed)
    assert all(not field.toPlainText() if hasattr(field, "toPlainText") else not field.text() for field in dialog.fields.values())
    dialog.fields["name"].setText("ECU")
    dialog.save_button.click()
    assert spy.count() == 0
    assert dialog.error_label.text()


def test_default_zipy_criteria_are_visible_and_editable_on_first_open(qtbot):
    dialog = ValidationPanel()
    qtbot.addWidget(dialog)
    dialog.set_settings(AppSettings())
    assert dialog.fields["source_mac_prefix"].text() == "02:00:00"
    assert dialog.fields["minimum_pps"].text() == "100"
    assert dialog.fields["grace_ms"].text() == "5000"


def test_user_supplied_rule_saved_and_removable_with_no_capture_filter(qtbot):
    dialog = ValidationPanel()
    qtbot.addWidget(dialog)
    dialog.set_settings(AppSettings(monitor_rules_json=""))
    values = {"name": "ECU", "destination_ip": "192.0.2.100", "expected_ip": "192.0.2.1",
              "timeout_ms": "1000", "grace_ms": "0", "max_delay_ms": "250", "recovery_count": "2"}
    for key, value in values.items():
        dialog.fields[key].setText(value)
    spy = QSignalSpy(dialog.preferences_changed)
    dialog.save_button.click()
    patch = spy.at(0)[0]
    saved = parse_rules(patch["monitor_rules_json"])
    assert saved[0].expected_ip == "192.0.2.1" and saved[0].grace_ms == 0
    assert set(patch) == {"monitor_rules_json"}
    dialog.set_settings(replace(AppSettings(), **patch))
    assert dialog.rule_combo.currentData() == saved[0].id
    dialog.delete_button.click()
    assert not parse_rules(spy.at(1)[0]["monitor_rules_json"])


def test_monitor_remains_viewable_while_recording_and_language_changes_preserve_draft(qtbot, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    window = MainWindow()
    qtbot.addWidget(window)
    window.settings_dialog.validation_panel.fields["name"].setText("unsaved criterion")
    window.set_language("en")
    assert window.settings_dialog.validation_panel.fields["name"].text() == "unsaved criterion"
    window.set_phase(SessionPhase.RECORDING)
    assert window.settings_button.isEnabled()
    window.settings_dialog.open_section("validation")
    window.settings_dialog.show()
    assert window.settings_dialog.isVisible()
    assert not window.settings_dialog.validation_panel.save_button.isEnabled()
    target = TargetSnapshot(Role.CAN, observation=ObservationState.UNSUPPORTED,
                            observation_details={"reasons": ["canoe_receive_events_unavailable"]})
    window.set_target(target)
    assert "unsupported" in window.observation_labels[Role.CAN].toolTip()


def test_ui_watchdog_drops_stale_normal_display_while_capture_continues(qtbot, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    window = MainWindow()
    qtbot.addWidget(window)
    window.set_phase(SessionPhase.RECORDING)
    report = {"status": "normal", "sampled_epoch": time.time() - 10,
              "rules": [{"name": "ECU", "status": "normal", "reasons": [], "max_delay_ms": 500}]}
    window.set_target(TargetSnapshot(Role.ETHERNET, observation=ObservationState.NORMAL, observation_details=report))
    window.check_monitor_freshness()
    assert window._targets[Role.ETHERNET].observation == ObservationState.UNKNOWN
    assert window._phase == SessionPhase.RECORDING
    assert "감시 응답 지연" in window.observation_labels[Role.ETHERNET].toolTip()
