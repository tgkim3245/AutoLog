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
from vil_logging.ui.monitor_dialog import MonitorDialog


def test_rule_fields_start_empty_and_partial_criteria_cannot_save(qtbot):
    dialog = MonitorDialog()
    qtbot.addWidget(dialog)
    spy = QSignalSpy(dialog.preferences_changed)
    assert all(not field.text() for field in dialog.fields.values())
    dialog.fields["name"].setText("ECU")
    dialog.save_button.click()
    assert spy.count() == 0
    assert dialog.error_label.text()


def test_user_supplied_rule_saved_and_removable_with_no_capture_filter(qtbot):
    dialog = MonitorDialog()
    qtbot.addWidget(dialog)
    dialog.set_settings(AppSettings())
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
    window.monitor_dialog.fields["name"].setText("unsaved criterion")
    window.set_language("en")
    assert window.monitor_dialog.fields["name"].text() == "unsaved criterion"
    window.set_phase(SessionPhase.RECORDING)
    assert window.monitor_button.isEnabled()
    window.monitor_button.click()
    assert window.monitor_dialog.isVisible()
    assert not window.monitor_dialog.save_button.isEnabled()
    target = TargetSnapshot(Role.CAN, observation=ObservationState.UNSUPPORTED,
                            observation_details={"reasons": ["canoe_receive_events_unavailable"]})
    window.set_target(target)
    assert "unsupported" in window.monitor_dialog.details.toPlainText()


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
    assert "감시 응답 지연" in window.monitor_dialog.details.toPlainText()
