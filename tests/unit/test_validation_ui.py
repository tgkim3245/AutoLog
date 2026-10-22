"""Validation settings and nonblocking, once-per-session user notifications."""

import json
from dataclasses import asdict, replace

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QMessageBox

from vil_logging.contracts.models import SessionPhase
from vil_logging.monitors.rules import (
    DEFAULT_POPUP_MESSAGE,
    DEFAULT_RULE_NAME,
    default_rules_json,
    encode_rules,
    parse_rules,
    upgrade_default_popup,
)
from vil_logging.ui.main_window import MainWindow
from vil_logging.ui.settings_dialog import SettingsDialog


def test_validation_tab_saves_multiline_popup_message_without_changing_criteria(qtbot):
    settings = SettingsDialog()
    qtbot.addWidget(settings)
    assert settings.tabs.tabText(3) == "zipy 유효성검사"
    assert not hasattr(settings, "environment_button")
    panel = settings.validation_panel
    assert panel.fields["name"].text() == DEFAULT_RULE_NAME
    assert panel.fields["popup_message"].toPlainText() == DEFAULT_POPUP_MESSAGE
    text = "사용자 안내 <b>그대로</b>\n|6 → e1"
    panel.fields["popup_message"].setPlainText(text)
    spy = QSignalSpy(settings.preferences_changed)
    panel.save_button.click()
    assert spy.count() == 1
    rules = parse_rules(spy.at(0)[0]["monitor_rules_json"])
    assert rules[0].popup_message == text
    assert rules[0].source_mac_prefix == "02:00:00" and rules[0].minimum_pps == 100
    settings.set_busy(True)
    assert not panel.save_button.isEnabled() and not panel.fields["popup_message"].isEnabled()


def test_popup_is_plain_nonmodal_once_per_session_and_does_not_block_x(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.set_phase(SessionPhase.RECORDING)
    rule = asdict(parse_rules(default_rules_json())[0])
    rule["popup_message"] = "<b>literal</b>\n|6 → e1"
    report = {"session_id": "session", "rules": [rule]}
    window.show_validation_failure(report)
    window.show_validation_failure(report)
    assert len(window._validation_alerts) == 1
    alert = window._validation_alerts[0]
    assert alert.text() == rule["popup_message"] and not alert.isModal()
    assert alert.textFormat() == Qt.TextFormat.PlainText
    assert window.logging_button.isEnabled()
    spy = QSignalSpy(window.exit_requested)
    window.close()
    assert spy.count() == 1
    alert.button(QMessageBox.StandardButton.Ok).click()
    assert not window._validation_alerts


def test_main_file_controls_are_adjacent_and_redundant_features_are_removed(qtbot, qapp):
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/malgun.ttf")
    old_font = qapp.font()
    qapp.setFont(QFont("Malgun Gothic", 9))
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    for width in (480, 360):
        window.resize(width, 760)
        qtbot.wait(20)
        assert window.file_manager_button.y() == window.delete_button.y()
        assert window.file_manager_button.x() < window.delete_button.x()
        folder_position = window.debug_folder_button.mapTo(window, QPoint(0, 0))
        history_position = window.file_manager_button.mapTo(window, QPoint(0, 0))
        assert folder_position.y() < history_position.y()
        assert window.debug_folder_button.geometry().center().y() == window.selection_count.geometry().center().y()
        assert window.main_scroll.horizontalScrollBar().maximum() == 0
    assert not any(hasattr(window, attr) for attr in ("quality_button", "monitor_button", "phase_label", "footer"))
    assert window.file_feedback.isHidden()
    assert not window.windowIcon().isNull()
    qapp.setFont(old_font)


def test_legacy_default_rule_gets_message_once_without_resetting_user_criteria():
    legacy = json.loads(default_rules_json())
    legacy["ethernet"][0].pop("popup_message")
    legacy["ethernet"][0].update(name="Zipy · 02:00:00", minimum_pps=55)
    upgraded = upgrade_default_popup(json.dumps(legacy))
    rule = parse_rules(upgraded)[0]
    assert rule.name == DEFAULT_RULE_NAME and rule.popup_message == DEFAULT_POPUP_MESSAGE
    assert rule.minimum_pps == 55
    assert upgrade_default_popup(upgraded) == upgraded
    custom = encode_rules([replace(rule, popup_message="", name="사용자 규칙")])
    assert upgrade_default_popup(custom) == custom
    assert upgrade_default_popup(encode_rules([])) == encode_rules([])


@pytest.mark.parametrize("message", ["x" * 2049, None, "bad\x00text"])
def test_invalid_popup_message_is_rejected(message):
    with pytest.raises(ValueError):
        replace(parse_rules(default_rules_json())[0], popup_message=message)
