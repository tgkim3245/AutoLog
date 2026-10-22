"""User-visible confirmations and file-operation locks."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QSystemTrayIcon

from vil_logging.contracts.models import SessionPhase
from vil_logging.ui import MainWindow
from vil_logging.ui.file_manager_dialog import DeleteFilesDialog


@pytest.fixture
def window(qtbot, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    window = MainWindow()
    qtbot.addWidget(window)
    window.set_capture_history([{"session_id": "previous", "index": 123, "prefix": "old_",
                                "current_name": "old_", "created_utc": "2026-10-18T01:00:00Z",
                                "can_rename": True, "files": [
        {"session_id": "previous", "role": "ethernet", "path": "C:/generated/old_123.pcap",
         "manageable": True, "status": "published", "identity": {"inode": 1}, "error": ""}]}])
    return window


def test_rename_uses_literal_filename_input_and_fixed_input_without_resizing(window):
    spy = QSignalSpy(window.rename_requested)
    window.show()
    before = window.size()
    window.previous_name.setText("new capture")
    window.rename_button.click()
    assert spy.at(0) == ["previous", "new capture"]
    assert window.size() == before


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter])
def test_enter_renames_previous_once_and_obeys_file_lock(window, qtbot, key):
    spy = QSignalSpy(window.rename_requested)
    window.show()
    window.previous_name.setText("새 이름")
    qtbot.keyClick(window.previous_name, key)
    assert spy.count() == 1 and spy.at(0) == ["previous", "새 이름"]
    window.set_file_busy(True)
    window.previous_name.returnPressed.emit()
    assert spy.count() == 1


def test_capture_and_file_operations_lock_mutating_controls(window):
    assert window.rename_button.isEnabled()
    window.set_file_busy(True)
    assert not window.rename_button.isEnabled()
    assert not window.delete_button.isEnabled()
    assert not window.logging_button.isEnabled()
    assert not window.settings_dialog.apply_button.isEnabled()
    window.set_file_busy(False)
    assert window.rename_button.isEnabled()
    window.set_phase(SessionPhase.RECORDING)
    assert not window.rename_button.isEnabled()
    assert window.file_manager.text.isReadOnly()
    assert window.logging_button.isEnabled()


def test_confirmation_lists_full_paths_and_defaults_to_cancel(qtbot):
    dialog = DeleteFilesDialog([{"path": "C:/generated/한글/old_123.pcap"},
                                {"path": "C:/generated/old_Diag_123.blf"}], "ko")
    qtbot.addWidget(dialog)
    assert "C:/generated/한글/old_123.pcap" in dialog.paths.toPlainText()
    assert "C:/generated/old_Diag_123.blf" in dialog.paths.toPlainText()
    assert dialog.cancel_button.isDefault()
    assert not dialog.confirm_button.isDefault()
    assert not dialog.confirm_button.autoDefault()


@pytest.mark.parametrize("accepted", [False, True])
def test_previous_delete_only_emits_after_confirmation(window, monkeypatch, accepted):
    observed = []

    def confirm(files, language, parent):
        observed.extend(files)
        assert files[0]["path"] == "C:/generated/old_123.pcap"
        return accepted

    monkeypatch.setattr("vil_logging.ui.main_window.confirm_delete", confirm)
    spy = QSignalSpy(window.delete_files_requested)
    window.delete_button.click()
    assert observed
    assert spy.count() == int(accepted)


def test_result_survives_busy_completion_and_language_change(window):
    result = {"status": "partial", "kind": "delete", "items": [
        {"source": "C:/generated/old_123.pcap", "status": "failed", "error": "sharing violation"}]}
    window.set_file_busy(True)
    window.set_file_result(result)
    window.set_file_busy(False)
    assert "일부" in window.file_feedback.text()
    assert "sharing violation" in window.file_manager.result_details.toPlainText()
    window.set_language("en")
    assert "Partial" in window.file_feedback.text()
    assert window.file_manager.windowTitle() == "Operation history"


def test_main_history_opens_read_only_operations_and_keeps_folder_adjacent(window):
    from PySide6.QtWidgets import QPushButton
    history = [{"created_utc": "2026-10-22T10:00:00Z", "kind": "rename", "status": "completed",
                "document": {"items": [{"source": "C:/generated/before.blf", "destination": "C:/generated/after.blf",
                                        "status": "renamed"}]}}]
    window.file_manager.set_operations(history)
    spy = QSignalSpy(window.files_refresh_requested)
    window.file_manager_button.click()
    assert spy.count() == 1 and window.file_manager.isVisible()
    text = window.file_manager.text.toPlainText()
    assert "before.blf" in text and "after.blf" in text
    assert window.file_manager.text.isReadOnly()
    assert not hasattr(window.file_manager, "delete_button")
    assert not hasattr(window, "packet_window")
    assert not hasattr(window, "environment_button")
    assert window.debug_folder_button.parent() == window.file_manager_button.parent()
    assert not window.findChild(QPushButton, "openPacketsButton")
