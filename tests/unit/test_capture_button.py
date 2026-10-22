"""The main action must describe and permit only the current operation."""

import pytest
from PySide6.QtTest import QSignalSpy

from vil_logging.contracts.models import ConnectionState, Role, SessionPhase, TargetSnapshot
from vil_logging.ui.main_window import MainWindow


@pytest.fixture
def window(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
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
