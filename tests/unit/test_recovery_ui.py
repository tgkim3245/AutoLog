from copy import deepcopy

import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QSystemTrayIcon

from vil_logging.contracts.models import SessionPhase
from vil_logging.ui.main_window import MainWindow
from vil_logging.ui.recovery_dialog import RecoveryDialog


@pytest.fixture
def report():
    return {"sessions": [{"session_id": "abandoned", "token": "reviewed-evidence", "index": 12,
                          "phase": "incomplete", "demo": False, "files": [{
        "role": "can", "filename": "AutoLog_12.blf", "state": "unknown", "metadata": {},
        "temp_path": "C:/captures/.vil_work/abandoned/AutoLog_12.blf",
        "final_path": "C:/captures/AutoLog_12.blf", "candidates": [{
            "path": "C:/captures/.vil_work/abandoned/AutoLog_12.blf", "present": True,
            "identity": {"bytes": 144, "inode": 9}}]}]}], "operations": [], "live_session_id": ""}


def test_recovery_requires_explicit_stop_confirmation_and_resets_when_evidence_changes(qtbot, report):
    dialog = RecoveryDialog()
    qtbot.addWidget(dialog)
    dialog.set_report(report)
    assert not dialog.stopped_check.isChecked()
    assert not dialog.publish_button.isEnabled()
    assert not dialog.finish_button.isEnabled()
    spy = QSignalSpy(dialog.requested)
    dialog.stopped_check.setChecked(True)
    dialog.publish_button.click()
    assert spy.at(0)[0] == {"action": "publish", "session_id": "abandoned", "role": "can",
                            "token": "reviewed-evidence", "stopped": True}
    dialog.set_report(deepcopy(report))
    assert dialog.stopped_check.isChecked()
    changed = deepcopy(report)
    changed["sessions"][0]["token"] = "changed"
    dialog.set_report(changed)
    assert not dialog.stopped_check.isChecked()
    assert not dialog.publish_button.isEnabled()
    assert "C:/captures/AutoLog_12.blf" in dialog.details.toPlainText()


def test_live_unconfirmed_capture_only_allows_retrying_stop(qtbot, report):
    dialog = RecoveryDialog()
    qtbot.addWidget(dialog)
    dialog.set_report({**report, "live_session_id": "abandoned"})
    dialog.stopped_check.setChecked(True)
    assert not dialog.publish_button.isEnabled()
    assert not dialog.finish_button.isEnabled()
    assert not dialog.refresh_button.isEnabled()
    assert dialog.retry_button.isEnabled()
    spy = QSignalSpy(dialog.requested)
    dialog.retry_button.click()
    assert spy.at(0)[0] == {"action": "retry_stop"}
    dialog.set_locked(True)
    assert not dialog.retry_button.isEnabled()


def test_main_panel_exposes_recovery_when_incomplete_while_capture_stays_locked(qtbot, monkeypatch, report):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    window = MainWindow()
    qtbot.addWidget(window)
    window.set_phase(SessionPhase.INCOMPLETE)
    window.set_recovery(report)
    assert not window.recovery_button.isHidden()
    assert window.recovery_button.isEnabled()
    assert window.logging_button.isEnabled()
    start = QSignalSpy(window.logging_requested)
    window.logging_button.click()
    assert start.count() == 0
    assert window.recovery_dialog.isVisible()
    assert not window.recovery_dialog._locked
    window.set_file_busy(True)
    assert window.recovery_dialog._locked
    window.set_file_busy(False)
    window.set_language("en")
    assert window.recovery_dialog.windowTitle() == "Capture recovery"
    assert "1 incomplete" in window.recovery_button.text()
    window.set_recovery({"sessions": [], "operations": []})
    assert window.recovery_button.isHidden()
