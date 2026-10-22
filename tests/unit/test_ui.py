"""Behavior checks for user controls, not screenshots or widget construction details."""

import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QCheckBox, QSystemTrayIcon

from vil_logging.contracts.models import (
    AppEvent,
    AppSettings,
    ConnectionState,
    PacketSummary,
    Role,
    SessionPhase,
    TargetSnapshot,
)
from vil_logging.ui import MainWindow


@pytest.fixture
def window(qtbot, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    instance = MainWindow()
    qtbot.addWidget(instance)
    return instance


def test_bug_report_replaces_the_logging_checkbox_and_emits_request(window):
    assert window.findChild(QCheckBox, "developerLogCheckBox") is None
    assert window.bug_report_button.text() == "버그리포트"
    assert window.bug_report_button.isEnabled() is False
    spy = QSignalSpy(window.bug_report_requested)
    window.set_debug_status("C:/logs/AutoLog_developer.jsonl")
    assert window.bug_report_button.isEnabled()
    window.bug_report_button.click()
    assert spy.count() == 1


def test_backend_debug_status_enables_export_and_surfaces_errors(window):
    window.set_debug_status("C:/logs/AutoLog_developer.jsonl")
    assert "C:/logs/AutoLog_developer.jsonl" in window.bug_report_button.toolTip()
    assert window.debug_folder_button.isEnabled()
    assert "AutoLog_developer.jsonl" in window.debug_status.text()
    window.set_debug_status("C:/logs/AutoLog_developer.jsonl", "permission denied")
    assert "permission denied" in window.debug_status.text()


def test_capture_selection_does_not_require_or_create_a_connection(window):
    assert window.selected_roles() == (Role.CAN, Role.ETHERNET)
    prepare_spy = QSignalSpy(window.prepare_requested)
    window.role_checks[Role.CAN].setChecked(False)
    assert window.selected_roles() == (Role.ETHERNET,)
    window.role_checks[Role.CAN].setChecked(True)
    assert window.selected_roles() == (Role.CAN, Role.ETHERNET)
    assert window._targets[Role.CAN].connection == ConnectionState.DISCONNECTED
    assert prepare_spy.count() == 0
    window.set_target(TargetSnapshot(Role.DIAG, connection=ConnectionState.READY))
    assert Role.DIAG not in window.selected_roles()
    assert window.selected_roles() == (Role.CAN, Role.ETHERNET)


def test_language_switch_renders_existing_events_and_retains_external_error(window):
    window.add_event(AppEvent("APP_READY", original="External tool detail 0x80004005"))
    window.add_event(AppEvent("FUTURE_CODE", original="Original unknown message"))
    assert "프로그램 준비 완료" in window.event_list.item(0).text()
    window.set_language("en")
    assert "Log capture" in window.windowTitle()
    assert "Application ready" in window.event_list.item(0).text()
    assert "External tool detail 0x80004005" in window.event_list.item(0).text()
    assert "Original unknown message" in window.event_list.item(1).text()
    assert window.bug_report_button.text() == "Bug report"
    assert window.settings_dialog.apply_button.text() == "Apply"


def test_busy_phase_locks_settings_but_keeps_bug_report_available(window):
    window.set_phase(SessionPhase.PREPARING)
    assert all(not check.isEnabled() for check in window.role_checks.values())
    assert not window.settings_dialog.apply_button.isEnabled()
    assert not window.settings_dialog.fields["can_cfg"].isEnabled()
    assert window.logging_button.isEnabled()
    window.set_debug_status("C:/logs/AutoLog_developer.jsonl")
    assert window.bug_report_button.isEnabled()
    window.set_phase(SessionPhase.STOPPING)
    assert not window.logging_button.isEnabled()
    window.set_phase(SessionPhase.COMPLETED)
    assert all(check.isEnabled() for check in window.role_checks.values())
    assert window.settings_dialog.apply_button.isEnabled()


def test_settings_accept_large_index_and_wait_for_backend_confirmation(window):
    dialog = window.settings_dialog
    spy = QSignalSpy(window.settings_applied)
    value = 2**70
    dialog.fields["next_index"].setText(str(value))
    dialog.fields["can_cfg"].setText("C:/CAN/test.cfg")
    dialog._apply()
    assert spy.count() == 1
    requested = spy.at(0)[0]
    assert requested.next_index == value
    assert requested.can_cfg == "C:/CAN/test.cfg"
    assert window._settings.next_index == 1
    window.set_settings(requested)
    assert window._settings.next_index == value
    dialog.fields["next_index"].setText("-1")
    dialog._apply()
    assert spy.count() == 1
    assert dialog.feedback.text()


def test_event_list_has_a_hard_500_item_bound(window):
    for index in range(507):
        window.add_event(AppEvent("TEST_EVENT", original=f"event-{index}"))
    assert len(window._events) == 500
    assert window.event_list.count() == 500
    assert "event-7" in window.event_list.item(0).text()
    assert "event-506" in window.event_list.item(499).text()


def test_packet_display_is_bounded_and_pause_filter_do_not_drop_input(window, qtbot):
    packets = window.packet_window
    for index in range(1005):
        window.add_packet(PacketSummary(str(index), "10.0.0.1", "10.0.0.2", "TCP", 64))
    assert len(packets.packets) == 1000
    assert packets.packets[0].timestamp == "5"
    packets.show()
    packets.refresh()
    assert packets.model.rowCount() == 1000
    packets.pause_check.setChecked(True)
    window.add_packet(PacketSummary("latest", "10.1.1.1", "10.1.1.2", "UDP", 42))
    packets.refresh()
    assert packets.model.data(packets.model.index(999, 0)) == "1004"
    assert packets.packets[-1].timestamp == "latest"
    packets.pause_check.setChecked(False)
    packets.filter_input.setText("UDP")
    packets.refresh()
    assert packets.model.rowCount() == 1
    assert packets.model.data(packets.model.index(0, 0)) == "latest"
    assert len(packets.packets) == 1000
    packets.hide()
    window.add_packet(PacketSummary("while-hidden", "", "", "ARP", 60))
    assert packets.packets[-1].timestamp == "while-hidden"


def test_demo_file_actions_explain_that_no_files_are_created(qtbot, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    window = MainWindow(demo=True)
    qtbot.addWidget(window)
    assert "모의 데모" in window.demo_label.text()
    assert "실제 로그 파일을 만들지 않습니다" in window.footer.text()
    assert not window.rename_button.isEnabled()
    assert not window.delete_button.isEnabled()
    assert "실제 파일을 만들지 않아" in window.rename_button.toolTip()


def test_x_close_requests_orderly_exit_without_hiding(window):
    window.show()
    spy = QSignalSpy(window.exit_requested)
    window.close()
    assert spy.count() == 1
    assert window.isVisible()


def test_x_close_requests_orderly_exit_even_when_tray_is_available(qtbot, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    spy = QSignalSpy(window.exit_requested)
    window.close()
    assert spy.count() == 1
    assert window.isVisible()


def test_settings_applied_language_is_reflected_in_all_views(window):
    window.set_settings(AppSettings(language="en", ethernet_format="pcapng"))
    assert window.packet_button.text() == "Packets"
    assert window.target_formats[Role.ETHERNET].text() == ".pcapng"
    assert "AutoLog_1.pcapng" in window.file_names.text()
    assert window.packet_window.pause_check.text() == "Pause display"


def test_capture_preview_adds_delimiter_to_user_entered_prefix(window):
    window.set_settings(AppSettings(prefix="Trip", next_index=9, ethernet_format="pcap"))
    assert window.file_names.text() == "Trip_9.blf · Trip_9.pcap"


def test_incomplete_session_locks_settings_targets_and_capture_restart(window):
    window.set_phase(SessionPhase.INCOMPLETE)
    assert not window.logging_button.isEnabled()
    assert all(not check.isEnabled() for check in window.role_checks.values())
    assert not window.settings_dialog.apply_button.isEnabled()
    assert not window.settings_dialog.fields["next_index"].isEnabled()
    assert window.bug_report_button.isEnabled() is False


def test_demo_results_do_not_claim_real_files_completed(qtbot, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    instance = MainWindow(demo=True)
    qtbot.addWidget(instance)
    instance.set_phase(SessionPhase.RECORDING)
    assert "모의 기록 중" in instance.phase_label.text()
    instance.set_phase(SessionPhase.COMPLETED)
    instance.set_files(["VIL_1.pcap"], "demo_files")
    assert instance.phase_label.text() == "모의 종료 · 파일 미생성"
    assert "파일 미생성" in instance.subtitle.text()
    assert "파일 미생성" in instance.file_heading.text()
    instance.set_language("en")
    assert instance.phase_label.text() == "Simulation ended · no files created"
    assert "no files created" in instance.file_heading.text()


def test_public_restore_window_shows_hidden_panel(window):
    window.hide()
    window.restore_window()
    assert window.isVisible()


def test_settings_control_has_font_independent_icon_and_accessible_label(window):
    assert not window.settings_button.icon().isNull()
    assert not window.settings_button.text()
    assert window.settings_button.accessibleName() == "설정"
    window.set_language("en")
    assert window.settings_button.accessibleName() == "Settings"


def test_demo_completion_event_does_not_claim_real_file_storage(window):
    window.add_event(AppEvent("SESSION_COMPLETED", params={"demo": True, "files_created": False}))
    message = window.event_list.item(0).text()
    assert "실제 파일 미생성" in message
    assert "보관 완료" not in message
    window.set_language("en")
    assert "no capture files created" in window.event_list.item(0).text()


def test_language_request_uses_preference_patch_instead_of_stale_full_settings(window):
    preferences = QSignalSpy(window.preferences_changed)
    naming = QSignalSpy(window.settings_applied)
    window._change_language("en")
    assert preferences.count() == 1
    assert preferences.at(0)[0] == {"language": "en"}
    assert naming.count() == 0


def test_preparation_report_changes_language_without_claiming_target_is_ready(window):
    report = {
        "role": "ethernet", "status": "attention",
        "message_ko": "네트워크를 선택하세요.", "message_en": "Select a network.",
        "detail": "No interface selected",
    }
    window.set_preparation_report(report)
    assert window.subtitle.text() == "네트워크를 선택하세요."
    assert window._targets[Role.ETHERNET].connection == ConnectionState.DISCONNECTED
    window.set_language("en")
    assert window.subtitle.text() == "Select a network."
    assert "No interface selected" in window.subtitle.toolTip()


def test_full_event_details_remain_available_without_crowding_activity_list(window):
    window.add_event(AppEvent("APP_READY", params={"long_internal_field": "preserved-detail"}))
    assert "long_internal_field" not in window.event_list.item(0).text()
    assert "preserved-detail" in window.event_list.item(0).toolTip()


def test_completed_capture_does_not_show_stale_preparation_message(window):
    window.set_preparation_report({"role": "ethernet", "status": "ready", "detail": "",
                                   "message_ko": "패킷 기록은 시작하지 않았습니다.",
                                   "message_en": "Recording has not started."})
    window.set_phase(SessionPhase.RECORDING)
    window.set_phase(SessionPhase.COMPLETED)
    assert "보관" in window.subtitle.text()
    assert "시작하지" not in window.subtitle.text()
