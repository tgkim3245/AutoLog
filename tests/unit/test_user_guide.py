"""Guide entry point, source/frozen paths and browser dispatch."""

import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QUrlQuery
from PySide6.QtGui import QDesktopServices, QFont, QFontDatabase
from PySide6.QtTest import QSignalSpy

from vil_logging import APP_NAME, __version__, documentation
from vil_logging.contracts.models import SessionPhase
from vil_logging.ui.main_window import MainWindow

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def app_font(qapp):
    old = qapp.font()
    for filename in ("malgun.ttf", "segoeui.ttf", "msyh.ttc"):
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/" + filename)
    qapp.setFont(QFont("Malgun Gothic", 9))
    yield
    qapp.setFont(old)


def test_frozen_guide_is_found_beside_exe_independent_of_cwd(tmp_path, monkeypatch):
    package = tmp_path / "배포 폴더 with spaces"
    package.mkdir()
    guide = package / f"{APP_NAME}_User_Guide.html"
    guide.write_text("<html>local guide</html>", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(package / f"{APP_NAME}.exe"))
    monkeypatch.chdir(tmp_path)
    assert documentation.user_guide_path() == guide
    guide.unlink()
    (tmp_path / guide.name).write_text("Wrong guide in working directory", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        documentation.user_guide_path()


def test_source_run_renders_the_same_illustrated_guide_without_a_build(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(documentation, "__file__", str(ROOT / "src/vil_logging/documentation.py"))
    monkeypatch.setattr(documentation.tempfile, "gettempdir", lambda: str(tmp_path))
    path = documentation.user_guide_path()
    _metadata, expected = documentation.load_user_documentation(ROOT, APP_NAME, __version__)
    assert path.read_text(encoding="utf-8") == expected[path.name]
    assert path.is_relative_to(tmp_path)
    assert documentation.user_guide_path() == path
    assert [item.name for item in path.parent.iterdir()] == [path.name]


@pytest.mark.parametrize("accepted", [True, False])
@pytest.mark.parametrize("language,expected", [("ko", "ko"), ("en", "en"), ("zh", "zh"), ("unknown", "ko")])
def test_opener_passes_a_proper_local_file_url_and_reports_browser_failure(tmp_path, monkeypatch, accepted, language, expected):
    path = tmp_path / "한글 경로" / "One Click Log_User_Guide.html"
    calls = []
    monkeypatch.setattr(documentation, "user_guide_path", lambda: path)
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: calls.append(url) or accepted)
    if accepted:
        documentation.open_user_guide(language)
    else:
        with pytest.raises(OSError, match="browser"):
            documentation.open_user_guide(language)
    assert len(calls) == 1 and calls[0].isLocalFile()
    assert Path(calls[0].toLocalFile()) == path
    assert QUrlQuery(calls[0]).queryItemValue("lang") == expected


@pytest.mark.parametrize("language,label", [("ko", "사용법"), ("en", "Guide"), ("zh", "使用说明")])
def test_guide_control_is_left_of_bug_report_and_available_while_busy(qtbot, app_font, language, label):
    window = MainWindow()
    qtbot.addWidget(window)
    window.set_language(language)
    window.show()
    spy = QSignalSpy(window.user_guide_requested)
    assert window.user_guide_button.text() == label
    for width in (360, 480):
        window.resize(width, 660)
        qtbot.wait(10)
        assert window.user_guide_button.geometry().right() < window.bug_report_button.geometry().left()
        assert window.main_scroll.horizontalScrollBar().maximum() == 0
    for phase in (SessionPhase.IDLE, SessionPhase.RECORDING, SessionPhase.STOPPING):
        window.set_phase(phase)
        assert window.user_guide_button.isEnabled()
        window.user_guide_button.click()
    assert spy.count() == 3
