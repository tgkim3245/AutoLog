"""Default repair, durable migration and the user's replacement-rule cleanup."""

import sqlite3
from dataclasses import replace

import pytest
from PySide6.QtTest import QSignalSpy

from vil_logging.contracts.models import AppSettings
from vil_logging.monitors.rules import (
    DEFAULT_POPUP_MESSAGE,
    DEFAULT_RULE_ID,
    DEFAULT_RULE_NAME,
    DefaultRuleCapacityError,
    EthernetRule,
    default_rules_json,
    encode_rules,
    parse_rules,
    restore_default_rule,
    upgrade_zipy_defaults,
)
from vil_logging.storage.repository import Repository
from vil_logging.ui.i18n import tr
from vil_logging.ui.validation_panel import ValidationPanel


def workaround():
    return EthernetRule("user-replacement", "zipy 활성화 검사", 1000, 1000, 1000, 10,
                        source_mac_prefix="02:00:00", popup_message="지피 확인하세요.")


def custom(identifier="custom"):
    return EthernetRule(identifier, "Other ECU", 1500, 4000, 500, 3,
                        source_mac_prefix="aa:bb:cc", popup_message="Keep this instruction")


def test_upgrade_replaces_only_the_superseded_workaround_and_restores_two_second_defaults():
    rules = parse_rules(upgrade_zipy_defaults(encode_rules([workaround(), custom()])))
    default, preserved = rules
    assert default.id == DEFAULT_RULE_ID and default.name == DEFAULT_RULE_NAME
    assert default.grace_ms == default.timeout_ms == 2000
    assert default.minimum_pps == 100 and default.source_mac_prefix == "02:00:00"
    assert default.popup_message == DEFAULT_POPUP_MESSAGE
    assert preserved == custom()
    assert upgrade_zipy_defaults(encode_rules(rules)) == encode_rules(rules)


@pytest.mark.parametrize("patch", [{"name": "another rule"}, {"minimum_pps": 50},
                                    {"popup_message": "other advice"}, {"grace_ms": 2000}])
def test_similar_user_rules_are_not_mistaken_for_the_superseded_replacement(patch):
    user_rule = replace(workaround(), **patch)
    assert parse_rules(upgrade_zipy_defaults(encode_rules([user_rule])))[1] == user_rule


def test_upgrade_changes_old_factory_timings_but_preserves_other_builtin_edits():
    builtin = parse_rules(default_rules_json())[0]
    old = replace(builtin, timeout_ms=3000, grace_ms=5000, minimum_pps=42, popup_message="Keep")
    upgraded = parse_rules(upgrade_zipy_defaults(encode_rules([old])))[0]
    assert upgraded == replace(old, timeout_ms=2000, grace_ms=2000)
    custom_timing = replace(builtin, grace_ms=7000)
    assert parse_rules(upgrade_zipy_defaults(encode_rules([custom_timing]))) == (custom_timing,)


def test_manual_restore_preserves_other_rules_and_resets_the_builtin():
    builtin = replace(parse_rules(default_rules_json())[0], grace_ms=7000, popup_message="custom")
    restored = parse_rules(restore_default_rule(encode_rules([custom(), builtin])))
    assert restored == (custom(), parse_rules(default_rules_json())[0])
    full = [custom(str(i)) for i in range(16)]
    with pytest.raises(DefaultRuleCapacityError):
        restore_default_rule(encode_rules(full))
    assert len(parse_rules(restore_default_rule(encode_rules([*full[:15], builtin])))) == 16


def open_profile(tmp_path, rules):
    repo = Repository(tmp_path / "state.sqlite3")
    repo.load_settings(str(tmp_path))
    settings = repo.save_preferences({"monitor_rules_json": encode_rules(rules)})
    return repo, settings


def test_repair_is_durable_and_later_intentional_deletion_is_respected(tmp_path):
    repo, old = open_profile(tmp_path, [workaround()])
    try:
        status, settings = repo.restore_zipy_default_once()
        assert status == "restored" and settings.version == old.version + 1
        assert settings.monitor_rules_json == default_rules_json()
        assert sum(e.code == "ZIPY_DEFAULT_RESTORED" for e in repo.recent_events()) == 1
        repo.save_preferences({"monitor_rules_json": encode_rules([])})
    finally:
        repo.close()
    restarted = Repository(tmp_path / "state.sqlite3")
    try:
        status, settings = restarted.restore_zipy_default_once()
        assert status == "already_applied" and parse_rules(settings.monitor_rules_json) == ()
        with sqlite3.connect(restarted.db_path) as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
    finally:
        restarted.close()


def test_repair_rolls_back_settings_event_and_marker_together_on_storage_failure(tmp_path):
    repo, old = open_profile(tmp_path, [workaround()])
    try:
        with sqlite3.connect(repo.db_path) as connection:
            connection.execute("CREATE TRIGGER fail_marker BEFORE INSERT ON settings_migrations "
                               "BEGIN SELECT RAISE(ABORT, 'simulated failure'); END")
        with pytest.raises(sqlite3.IntegrityError, match="simulated failure"):
            repo.restore_zipy_default_once()
        assert repo.load_settings() == old
        assert not any(e.code == "ZIPY_DEFAULT_RESTORED" for e in repo.recent_events())
        with sqlite3.connect(repo.db_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM settings_migrations").fetchone()[0] == 0
            connection.execute("DROP TRIGGER fail_marker")
        assert repo.restore_zipy_default_once()[0] == "restored"
    finally:
        repo.close()


def test_full_profile_preserves_all_rules_and_can_be_repaired_when_space_is_available(tmp_path):
    repo, old = open_profile(tmp_path, [custom(str(i)) for i in range(16)])
    try:
        assert repo.restore_zipy_default_once() == ("limit", old)
        repo.save_preferences({"monitor_rules_json": encode_rules(parse_rules(old.monitor_rules_json)[:15])})
        status, settings = repo.restore_zipy_default_once()
        assert status == "restored" and len(parse_rules(settings.monitor_rules_json)) == 16
        assert parse_rules(settings.monitor_rules_json)[0].id == DEFAULT_RULE_ID
    finally:
        repo.close()


@pytest.mark.parametrize("language", ["ko", "en", "zh"])
def test_restore_selects_the_builtin_and_waits_for_saved_settings(qtbot, language):
    panel = ValidationPanel()
    qtbot.addWidget(panel)
    panel.set_language(language)
    old = AppSettings(monitor_rules_json=encode_rules([custom()]))
    panel.set_settings(old)
    spy = QSignalSpy(panel.preferences_changed)
    assert panel.restore_button.text() == tr("monitor_restore_default", language)
    panel.restore_button.click()
    assert spy.count() == 1 and not panel.save_button.isEnabled()
    patch = spy.at(0)[0]
    assert parse_rules(patch["monitor_rules_json"])[1] == custom()
    panel.set_settings(replace(old, **patch))
    assert panel.save_button.isEnabled()
    assert panel.rule_combo.currentData() == DEFAULT_RULE_ID
    assert panel.fields["grace_ms"].text() == panel.fields["timeout_ms"].text() == "2000"
    panel.rule_combo.setCurrentIndex(panel.rule_combo.findData("custom"))
    panel.fields["name"].setText("unsaved custom draft")
    panel.restore_button.click()  # Already-default JSON: select it without waiting for a no-op save.
    assert spy.count() == 1 and panel.rule_combo.currentData() == DEFAULT_RULE_ID
    assert panel.fields["name"].text() == DEFAULT_RULE_NAME
    panel.save_button.click()
    assert parse_rules(spy.at(1)[0]["monitor_rules_json"])[0] == custom()


def test_restore_can_retry_after_save_error_and_is_disabled_during_capture(qtbot):
    panel = ValidationPanel()
    qtbot.addWidget(panel)
    panel.set_settings(AppSettings(monitor_rules_json=encode_rules([])))
    spy = QSignalSpy(panel.preferences_changed)
    panel.set_locked(True)
    panel.restore_button.click()
    assert spy.count() == 0
    panel.set_locked(False)
    panel.restore_button.click()
    panel.set_error("Simulated disk error")
    assert panel.restore_button.isEnabled()
    panel.restore_button.click()
    assert spy.count() == 2


def test_restore_does_not_discard_a_rule_when_the_limit_is_reached(qtbot):
    panel = ValidationPanel()
    qtbot.addWidget(panel)
    panel.set_settings(AppSettings(monitor_rules_json=encode_rules([custom(str(i)) for i in range(16)])))
    spy = QSignalSpy(panel.preferences_changed)
    panel.restore_button.click()
    assert spy.count() == 0 and panel.restore_button.isEnabled()
    assert panel.error_label.text() == tr("monitor_restore_default_limit", "ko")
