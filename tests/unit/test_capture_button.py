"""The main action must describe and permit only the current operation."""

from dataclasses import replace

import pytest
from PySide6.QtTest import QSignalSpy

from vil_logging.contracts.models import (
    AppSettings,
    ConnectionState,
    Role,
    SessionPhase,
    TargetSnapshot,
)
from vil_logging.ui.main_window import MainWindow


@pytest.fixture
def window(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.set_settings(AppSettings(output_dir="C:/generated", can_cfg="C:/project/CAN.cfg",
                                    can_logging_block="1", nic_id="example-ethernet"))
    for role in window.selected_roles():
        window.set_target(TargetSnapshot(role, connection=ConnectionState.READY))
    return window


@pytest.mark.parametrize("phase,text,enabled,tone", [
    (SessionPhase.IDLE, "기록 시작", True, "success"),
    (SessionPhase.PREPARING, "준비 중 · 취소", True, "attention"),
    (SessionPhase.STARTING, "시작 중 · 취소", True, "attention"),
    (SessionPhase.RECORDING, "기록 중 · 정지", True, "stop"),
    (SessionPhase.PARTIAL, "일부 기록 중 · 정지", True, "attention"),
    (SessionPhase.STOPPING, "정지 · 파일 정리 중…", False, "progress"),
    (SessionPhase.COMPLETED, "다음 기록 시작", True, "success"),
    (SessionPhase.FAILED, "새 기록 시작", True, "success"),
    (SessionPhase.INCOMPLETE, "기록 마무리 확인", False, "attention"),
])
def test_phase_describes_action_and_click_availability(window, phase, text, enabled, tone):
    window.set_phase(phase)
    button = window.logging_button
    assert button.text() == text and button.isEnabled() == enabled
    assert button.property("tone") == tone
    assert button.accessibleName() == text


def test_cancel_is_requested_once_and_does_not_reenable_during_start_transition(window):
    spy = QSignalSpy(window.logging_requested)
    window.set_phase(SessionPhase.PREPARING)
    window.logging_button.click()
    window.logging_button.click()
    assert spy.count() == 1 and not window.logging_button.isEnabled()
    assert window.logging_button.text() == "취소 처리 중…"
    window.set_phase(SessionPhase.STARTING)
    assert not window.logging_button.isEnabled()
    window.set_phase(SessionPhase.FAILED)
    assert window.logging_button.isEnabled() and window.logging_button.text() == "새 기록 시작"


def test_stop_remains_available_during_background_checks_and_cannot_be_double_clicked(window):
    spy = QSignalSpy(window.logging_requested)
    window.set_target(TargetSnapshot(Role.DIAG, connection=ConnectionState.CONNECTING))
    window.set_phase(SessionPhase.RECORDING)
    assert window.logging_button.isEnabled()
    window.logging_button.click()
    assert window.logging_button.text() == "정지 요청 중…"
    window.logging_button.click()
    assert spy.count() == 1
    window.set_phase(SessionPhase.STOPPING)
    window.set_capture_step({"step": "checking_file", "target": "CAN"})
    assert window.logging_button.text() == "CAN 파일 검사 중…"
    window.set_capture_step({"step": "saving", "target": "Zipy"})
    assert window.logging_button.text() == "Zipy 파일 저장 중…"
    assert not window.logging_button.isEnabled()
    window.set_target(TargetSnapshot(Role.DIAG, connection=ConnectionState.READY))
    window.set_phase(SessionPhase.COMPLETED)
    assert window.logging_button.text() == "다음 기록 시작"


def test_loading_connection_file_work_and_exit_are_visible_and_block_start(window):
    button = window.logging_button
    window.set_initializing(True)
    assert button.text() == "프로그램 준비 중…" and not button.isEnabled()
    window.set_initializing(False, failed=True)
    assert button.text() == "초기화 실패" and not button.isEnabled()
    window.set_initializing(False)
    window.set_target(TargetSnapshot(Role.CAN, connection=ConnectionState.CONNECTING))
    assert button.text() == "CAN 연결 중…" and not button.isEnabled()
    window.set_target(TargetSnapshot(Role.CAN, connection=ConnectionState.READY))
    window.set_file_busy(True)
    assert button.text() == "파일 처리 중…" and not button.isEnabled()
    window.set_exiting(True)
    window.set_phase(SessionPhase.COMPLETED)
    assert button.text() == "종료 준비 중…" and not button.isEnabled()
    window.set_exiting(False)
    window.set_file_busy(False)
    assert button.isEnabled()
    for check in window.role_checks.values():
        check.setChecked(False)
    assert button.text() == "대상을 선택하세요" and not button.isEnabled()


def test_incomplete_button_opens_recovery_instead_of_starting_capture(window):
    spy = QSignalSpy(window.logging_requested)
    window.set_phase(SessionPhase.INCOMPLETE)
    window.set_recovery({"sessions": [], "operations": [], "live_session_id": "current"})
    assert window.logging_button.isEnabled()
    window.logging_button.click()
    assert spy.count() == 0 and window.recovery_dialog.isVisible()
    assert window.recovery_dialog.retry_button.isEnabled()


def test_language_changes_and_progress_indicator_follow_current_state(window, qtbot):
    window.show()
    window.set_phase(SessionPhase.STARTING)
    button = window.logging_button
    qtbot.waitUntil(lambda: button._timer.isActive())
    assert not button.icon().isNull()
    window.set_language("en")
    assert button.text() == "Starting · Cancel"
    window.set_language("zh")
    assert button.text() == "正在启动 · 取消"
    window.set_phase(SessionPhase.RECORDING)
    assert not button._timer.isActive() and button.icon().isNull()
    window.set_phase(SessionPhase.STOPPING)
    window.hide()
    assert not button._timer.isActive()


def test_first_launch_opens_missing_settings_without_requesting_capture(qtbot):
    fresh = MainWindow()
    qtbot.addWidget(fresh)
    spy = QSignalSpy(fresh.logging_requested)
    assert fresh.logging_button.text() == "환경 설정 필요"
    assert fresh.logging_button.property("tone") == "neutral"
    fresh.logging_button.click()
    assert spy.count() == 0 and fresh.settings_dialog.isVisible()
    assert fresh.settings_dialog.tabs.currentIndex() == 0


@pytest.mark.parametrize("patch,tab,text", [
    ({"output_dir": ""}, 0, "환경 설정 필요"),
    ({"can_cfg": ""}, 1, "환경 설정 필요"),
    ({"nic_id": ""}, 2, "환경 설정 필요"),
    ({"can_logging_block": ""}, 1, "연결 확인 필요"),
    ({"nic_id": "new-network"}, 2, "연결 확인 필요"),
    ({"tshark_path": "C:/Other/tshark.exe"}, 2, "연결 확인 필요"),
    ({"can_cfg": "C:/project/new.cfg"}, 1, "연결 확인 필요"),
])
def test_missing_or_changed_configuration_routes_to_the_correct_tab(window, patch, tab, text):
    spy = QSignalSpy(window.logging_requested)
    window.set_settings(replace(window._settings, **patch))
    assert window.logging_button.text() == text and window.logging_button.property("tone") != "success"
    window.logging_button.click()
    assert spy.count() == 0 and window.settings_dialog.tabs.currentIndex() == tab


def test_remembered_paths_are_not_treated_as_checked_connections(qtbot):
    fresh = MainWindow()
    qtbot.addWidget(fresh)
    fresh.set_settings(AppSettings(output_dir="C:/generated", can_cfg="C:/project/CAN.cfg",
                                  can_logging_block="1", nic_id="example-ethernet"))
    assert fresh.logging_button.text() == "연결 확인 필요"
    fresh.set_target(TargetSnapshot(Role.CAN, connection=ConnectionState.READY))
    assert fresh.logging_button.text() == "연결 확인 필요"
    fresh.logging_button.click()
    assert fresh.settings_dialog.tabs.currentIndex() == 2
    fresh.set_target(TargetSnapshot(Role.ETHERNET, connection=ConnectionState.READY))
    assert fresh.logging_button.text() == "기록 시작" and fresh.logging_button.property("tone") == "success"


def test_only_selected_targets_need_configuration_and_connection(window):
    window.set_settings(replace(window._settings, can_cfg="", can_logging_block=""))
    window.role_checks[Role.CAN].setChecked(False)
    assert window.logging_button.text() == "기록 시작"
    window.role_checks[Role.CAN].setChecked(True)
    assert window.logging_button.text() == "환경 설정 필요"


def test_storage_name_and_index_edits_do_not_require_reconnecting(window):
    window.set_settings(replace(window._settings, output_dir="C:/new-output", prefix="Changed", next_index=12))
    assert window.logging_button.text() == "기록 시작" and window.logging_button.property("tone") == "success"


@pytest.mark.parametrize("phase", [SessionPhase.COMPLETED, SessionPhase.FAILED])
def test_repeat_start_is_green_only_when_selected_connections_are_still_ready(window, phase):
    window.set_phase(phase)
    assert window.logging_button.property("tone") == "success"
    window.set_target(TargetSnapshot(Role.ETHERNET, connection=ConnectionState.ERROR))
    assert window.logging_button.text() == "연결 확인 필요" and window.logging_button.property("tone") == "neutral"
    window.set_target(TargetSnapshot(Role.ETHERNET, connection=ConnectionState.READY))
    assert window.logging_button.property("tone") == "success"


def measurement_waiting(window, **patch):
    window.set_target(TargetSnapshot(Role.CAN, connection=ConnectionState.UNKNOWN))
    window.set_preparation_report({"role": "can", "status": "attention", "readiness_stage": "measurement_waiting",
        "connected_cfg": "c:\\PROJECT\\can.cfg", "selected_block": "1", **patch})


def test_f9_can_be_started_externally_then_checked_by_start_without_reconnecting(window):
    measurement_waiting(window)
    assert window.logging_button.text() == "CANoe 측정 확인 후 시작"
    assert window.logging_button.property("tone") == "attention"
    assert "F9" in window.subtitle.text()
    spy = QSignalSpy(window.logging_requested)
    window.logging_button.click()
    assert spy.count() == 1 and not window.settings_dialog.isVisible()
    window.set_target(TargetSnapshot(Role.CAN, connection=ConnectionState.READY))
    window.set_phase(SessionPhase.COMPLETED)
    assert window.logging_button.text() == "다음 기록 시작"
    assert "측정" not in window.target_states[Role.CAN].text()


@pytest.mark.parametrize("patch", [
    {"connected_cfg": "C:/project/other.cfg"}, {"selected_block": "2"},
    {"readiness_stage": "license_required"}, {"readiness_stage": "hardware_mismatch"},
    {"readiness_stage": "block_recording"}, {"connected_cfg": None},
])
def test_stale_or_blocked_canoe_checks_cannot_use_the_measurement_waiting_shortcut(window, patch):
    measurement_waiting(window, **patch)
    spy = QSignalSpy(window.logging_requested)
    assert window.logging_button.text() == "연결 확인 필요"
    window.logging_button.click()
    assert spy.count() == 0 and window.settings_dialog.tabs.currentIndex() == 1


@pytest.mark.parametrize("language,text", [("ko", "환경 설정 필요"), ("en", "Setup required"), ("zh", "需要设置")])
def test_setup_state_is_localized(qtbot, language, text):
    fresh = MainWindow()
    qtbot.addWidget(fresh)
    fresh.set_language(language)
    assert fresh.logging_button.text() == text


def test_demo_keeps_simulation_start_without_real_configuration(qtbot):
    demo = MainWindow(demo=True)
    qtbot.addWidget(demo)
    spy = QSignalSpy(demo.logging_requested)
    assert demo.logging_button.text() == "모의 · 기록 시작"
    demo.logging_button.click()
    assert spy.count() == 1
