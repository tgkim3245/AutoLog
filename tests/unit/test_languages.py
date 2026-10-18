from string import Formatter

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QSystemTrayIcon

from vil_logging.contracts.models import AppEvent, AppSettings, Role
from vil_logging.storage.repository import Repository
from vil_logging.ui import MainWindow, i18n, zh_cn
from vil_logging.ui.settings_dialog import TEXT as SETTINGS_TEXT


def placeholders(text):
    return {name for _, name, _, _ in Formatter().parse(text) if name is not None}


def test_chinese_catalog_covers_labels_events_and_keeps_format_fields():
    for original, chinese in [(i18n.TEXT, zh_cn.TEXT), (i18n.EVENTS, zh_cn.EVENTS),
                              (i18n.DEMO_EVENTS, zh_cn.DEMO_EVENTS), (SETTINGS_TEXT, zh_cn.SETTINGS)]:
        assert not original.keys() - chinese.keys()
        for key, pair in original.items():
            assert chinese[key]
            assert placeholders(pair[1]) == placeholders(chinese[key]), key


def test_one_language_button_cycles_all_views_and_emits_persisted_choice(qtbot, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    window = MainWindow()
    qtbot.addWidget(window)
    spy = QSignalSpy(window.preferences_changed)
    assert window.selected_roles() == (Role.CAN, Role.ETHERNET)
    window.language_button.click()
    assert window.packet_button.text() == "Packets"
    window.language_button.click()
    assert window._language == "zh"
    assert spy.at(1)[0] == {"language": "zh"}
    assert window.settings_dialog.apply_button.text() == "应用"
    assert window.file_manager.close_button.text() == "关闭"
    assert window.monitor_dialog.windowTitle() == "通信监测"
    window.add_event(AppEvent("APP_READY", original="Error 0x80004005"))
    assert "程序已就绪" in window.event_list.item(0).text()
    assert "0x80004005" in window.event_list.item(0).text()
    window.language_button.click()
    assert window._language == "ko"
    assert not hasattr(window, "title_label") and not hasattr(window, "status_pill")
    assert not hasattr(window.settings_dialog, "exit_button")


def test_chinese_preference_survives_restart(tmp_path):
    path = tmp_path / "state.sqlite3"
    repo = Repository(path)
    try:
        repo.load_settings()
        repo.save_preferences({"language": "zh"})
    finally:
        repo.close()
    repo = Repository(path)
    try:
        assert repo.load_settings().language == "zh"
        assert AppSettings().language == "ko"
    finally:
        repo.close()
