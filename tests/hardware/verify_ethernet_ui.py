"""Explicit localhost-only UI integration, outside the default automated suite."""

import json
import os
import socket
import time
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from vil_logging import runtime as runtime_module
from vil_logging import ui
from vil_logging.app import main
from vil_logging.contracts.models import Role, SessionPhase
from vil_logging.ui.file_manager_dialog import DeleteFilesDialog


def verify():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    root = Path(os.environ["LOCALAPPDATA"]) / "AutoLog/development/ethernet-ui-verification" / uuid4().hex
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    port = receiver.getsockname()[1]
    original_runtime = runtime_module.Runtime
    outcome = {"passed": False, "profile": str(root), "physical_nic_opened": False}

    class VerificationRuntime(original_runtime):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, _verification_filter=f"udp dst port {port}", **kwargs)

    class VerificationWindow(ui.MainWindow):
        def __init__(self, *args, **kwargs):
            QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\malgun.ttf")
            super().__init__(*args, **kwargs)
            self.step = 0
            self.tick = QTimer(self)
            self.tick.setInterval(50)
            self.tick.timeout.connect(self.advance)
            self.tick.start()
            QTimer.singleShot(45_000, lambda: QApplication.instance().exit(5))

        def send(self, count):
            for _ in range(count):
                sender.sendto(("VIL-ui-verification-" + uuid4().hex).encode(), ("127.0.0.1", port))

        def advance(self):
            try:
                dialog, packets = self.settings_dialog, self.packet_window
                if self.step == 0 and self._discovery_report and self._settings.tshark_path:
                    assert self.bug_report_button.isEnabled()
                    dialog.open_section("ethernet")
                    index = dialog.nic_input.findData(r"\Device\NPF_Loopback")
                    assert index >= 0
                    dialog.nic_input.setCurrentIndex(index)
                    self.step = 1
                elif self.step == 1 and self._settings.nic_id == r"\Device\NPF_Loopback":
                    dialog.prepare_buttons[Role.ETHERNET].click()
                    self.step = 2
                elif self.step == 2 and dialog._reports.get(Role.ETHERNET, {}).get("status") == "ready":
                    dialog.hide()
                    self.logging_button.click()
                    self.step = 3
                elif self.step == 3 and self._phase == SessionPhase.RECORDING:
                    packets.show()
                    packets.pause_check.setChecked(True)
                    self.send(5)
                    self.step = 4
                elif self.step == 4 and len(packets.packets) == 5:
                    assert packets.table.rowCount() == 0
                    packets.hide()
                    self.send(3)
                    self.step = 5
                elif self.step == 5 and len(packets.packets) == 8:
                    packets.show()
                    packets.pause_check.setChecked(False)
                    packets.refresh()
                    assert packets.table.rowCount() == 8
                    self.logging_button.click()
                    self.step = 6
                elif self.step == 6 and self._phase == SessionPhase.COMPLETED and self.rename_button.isEnabled():
                    assert len(self._files) == 1 and Path(self._files[0]).is_file()
                    assert self._settings.next_index == 2
                    packets.grab().save(str(root / "packets.png"))
                    self.initial_height = self.height()
                    self.previous_name.setText("UI_renamed")
                    self.rename_button.click()
                    self.step = 7
                elif self.step == 7 and self._files and Path(self._files[0]).name == "UI_renamed.pcap" and not self._file_busy:
                    assert self.height() == self.initial_height
                    assert Path(self._files[0]).is_file()
                    self.grab().save(str(root / "main.png"))
                    self.file_manager_button.click()
                    self.file_manager.grab().save(str(root / "files.png"))
                    self.file_manager.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
                    # Reject the real confirmation dialog, then accept a fresh one.
                    # The only candidate is the localhost capture this test just made.
                    def cancel():
                        active = QApplication.activeModalWidget()
                        assert isinstance(active, DeleteFilesDialog)
                        assert self._files[0] in active.paths.toPlainText()
                        active.grab().save(str(root / "delete-confirmation.png"))
                        active.cancel_button.click()
                    self.step = 8
                    self.tick.stop()
                    QTimer.singleShot(50, cancel)
                    self.file_manager.delete_button.click()
                    assert Path(self._files[0]).is_file()
                    def accept():
                        active = QApplication.activeModalWidget()
                        assert isinstance(active, DeleteFilesDialog)
                        active.confirm_button.click()
                    QTimer.singleShot(50, accept)
                    self.file_manager.delete_button.click()
                    self.tick.start()
                elif self.step == 8 and self._capture_history and self._capture_history[0]["files"][0]["status"] == "deleted" and not self._file_busy:
                    assert self._settings.next_index == 2
                    assert not self.rename_button.isEnabled()
                    self.file_manager.grab().save(str(root / "deleted.png"))
                    outcome.update(passed=True, packets_in_view=len(packets.packets),
                                   deleted_generated_file=self._capture_history[0]["files"][0]["path"],
                                   pause_and_hidden_capture_continued=True,
                                   renamed_without_resize=True, cancelled_delete_preserved=True,
                                   confirmed_delete=True, next_index=self._settings.next_index)
                    self.tick.stop()
                    self.exit_requested.emit()
            except Exception as error:
                outcome["error"] = repr(error)
                self.tick.stop()
                QApplication.instance().exit(5)

    runtime_module.Runtime = VerificationRuntime
    ui.MainWindow = VerificationWindow
    started = time.monotonic()
    result = main(["--data-dir", str(root)])
    receiver.close()
    sender.close()
    outcome.update(exit_code=result, elapsed_seconds=round(time.monotonic() - started, 2))
    (root / "ui_result.json").write_text(json.dumps(outcome, indent=2), encoding="utf-8")
    print(json.dumps(outcome))
    return 0 if outcome["passed"] and result == 0 else 2


if __name__ == "__main__":
    raise SystemExit(verify())
