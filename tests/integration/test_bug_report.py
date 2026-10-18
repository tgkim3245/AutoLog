import os
import subprocess
import sys
import textwrap
from pathlib import Path


def test_bug_report_button_exports_logs_and_shows_email_instructions(tmp_path):
    script = textwrap.dedent(r'''
        import sys
        import zipfile
        from pathlib import Path
        from PySide6.QtCore import QStandardPaths, QTimer
        from PySide6.QtWidgets import QApplication, QMessageBox
        from vil_logging import ui
        from vil_logging.app import main

        root = Path(sys.argv[1])
        desktop = root / "Desktop"
        QStandardPaths.writableLocation = staticmethod(lambda _location: str(desktop))
        dialogs = []
        QMessageBox.information = staticmethod(lambda _parent, title, message:
                                               dialogs.append((title, message)))
        QMessageBox.warning = staticmethod(lambda _parent, title, message:
                                           dialogs.append((title, message)))

        class ExercisedWindow(ui.MainWindow):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.exercise = QTimer(self)
                self.exercise.timeout.connect(self.export_and_exit)
                self.exercise.start(30)

            def export_and_exit(self):
                if not self.bug_report_button.isEnabled():
                    return
                self.exercise.stop()
                self.bug_report_button.click()
                QTimer.singleShot(0, self.exit_requested.emit)

        ui.MainWindow = ExercisedWindow
        result = main(["--data-dir", str(root / "app-data")])
        assert result == 0
        assert len(dialogs) == 1, dialogs
        title, message = dialogs[0]
        assert title == "버그리포트"
        assert "Taegon.Kim" in message
        assert "@" not in message
        assert "AutoLog_BugReport_" in message
        reports = list(desktop.glob("AutoLog_BugReport_*.zip"))
        assert len(reports) == 1
        assert reports[0].name in message
        with zipfile.ZipFile(reports[0]) as archive:
            assert "AutoLog_developer.jsonl" in archive.namelist()
            content = archive.read("AutoLog_developer.jsonl").decode("utf-8")
            assert "bug_report.export_requested" in content
        print("BUG_REPORT_BUTTON_PASSED", reports[0].name)
    ''')
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONDONTWRITEBYTECODE": "1",
                   "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")}
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)], env=environment,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "BUG_REPORT_BUTTON_PASSED" in completed.stdout
