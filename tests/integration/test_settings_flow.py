"""Exercise the actual app signal wiring and restore choices in a fresh process."""

import os
import subprocess
import sys
import textwrap
from pathlib import Path


def test_choices_and_prepare_feedback_survive_real_app_restart(tmp_path):
    captures = tmp_path / "selected-captures"
    captures.mkdir()
    script = textwrap.dedent(r'''
        import sys
        from pathlib import Path
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        from vil_logging import ui
        from vil_logging.app import main
        from vil_logging.contracts.models import Role
        from vil_logging.diagnostics import connections

        root, mode = Path(sys.argv[1]), sys.argv[2]
        cfg = str(root / "missing-but-remembered.cfg")
        output = str(root / "selected-captures")
        tool = str(root / "Wireshark" / "tshark.exe")
        report = {"tshark": {"status": "ready", "path": tool, "version": "TShark test"},
                  "interfaces": [{"id": "test-nic", "name": "Vehicle Ethernet", "status": "up",
                                  "capture_available": True}],
                  "selected_nic_id": "test-nic", "npcap": {"status": "present"}}
        connections.discover_connections = lambda *args: report
        outcome = {"passed": False, "error": ""}

        class ExercisedWindow(ui.MainWindow):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.step = 0
                self.exercise = QTimer(self)
                self.exercise.timeout.connect(self.advance)
                self.exercise.start(50)

            def advance(self):
                try:
                    if not self._settings.output_dir or not self._discovery_report:
                        return
                    assert self.bug_report_button is not None
                    dialog = self.settings_dialog
                    if mode == "edit" and self.step == 0:
                        self.step = 1
                        dialog.show()
                        for key, value in (("can_cfg", cfg), ("diag_cfg", cfg), ("output_dir", output), ("tshark_path", tool)):
                            dialog.fields[key].setText(value)
                            dialog.fields[key].editingFinished.emit()
                        dialog.nic_input.setCurrentIndex(dialog.nic_input.findData("test-nic"))
                        dialog.format_input.setCurrentText("pcapng")
                        dialog.fields["prefix"].setText("saved_")
                        dialog.fields["next_index"].setText("42")
                        dialog._apply()
                        dialog.tabs.setCurrentIndex(1)
                        dialog.prepare_buttons[Role.CAN].click()
                        assert not dialog.prepare_buttons[Role.CAN].isEnabled()
                        assert dialog._reports[Role.CAN]["status"] == "checking"
                        return
                    if mode == "edit":
                        result = dialog._reports.get(Role.CAN, {})
                        if result.get("status") != "error":
                            return
                        assert dialog.prepare_buttons[Role.CAN].isEnabled()
                        assert "다시 선택" in dialog.target_labels[Role.CAN].text()
                        assert dialog.next_actions[Role.CAN].text()
                    saved = self._settings
                    assert saved.can_cfg == cfg and saved.diag_cfg == cfg
                    assert saved.output_dir == output and saved.tshark_path == tool
                    assert saved.nic_id == "test-nic" and saved.ethernet_format == "pcapng"
                    assert saved.prefix == "saved_" and saved.next_index == 42
                    self.exercise.stop()
                    outcome["passed"] = True
                    self.exit_requested.emit()
                except BaseException as error:
                    outcome["error"] = repr(error)
                    self.exercise.stop()
                    QApplication.instance().exit(5)

        ui.MainWindow = ExercisedWindow
        result = main(["--data-dir", str(root / "profile")])
        assert outcome["passed"], outcome
        assert result == 0
        print("SETTINGS_FLOW_PASSED", mode)
    ''')
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")}
    for mode in ("edit", "restore"):
        completed = subprocess.run([sys.executable, "-c", script, str(tmp_path), mode],
                                   env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                   timeout=25, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert "SETTINGS_FLOW_PASSED" in completed.stdout
        assert "Traceback" not in completed.stderr
