from dataclasses import replace
from pathlib import Path

import pytest

from vil_logging.storage.profile_migration import migrate_legacy_profile
from vil_logging.storage.repository import Repository


@pytest.mark.parametrize(("old_prefix", "expected_prefix"), [
    ("VIL", "AutoLog"),
    ("Auto_Log", "AutoLog"),
    ("custom_run", "custom_run"),
])
def test_migrates_settings_and_preserves_capture_index(tmp_path: Path, old_prefix: str,
                                                       expected_prefix: str) -> None:
    legacy = tmp_path / "VILLogging"
    new = tmp_path / "AutoLog"
    (tmp_path / "my-captures").mkdir()
    old_db = Repository(legacy / "state.sqlite3")
    settings = old_db.load_settings(str(tmp_path / "my-captures"))
    old_db.save_settings(replace(settings, prefix=old_prefix, next_index=42,
                                 can_cfg="C:/can.cfg", nic_id="nic-123"), ())
    old_db.close()

    assert migrate_legacy_profile(legacy, new) is True

    migrated = Repository(new / "state.sqlite3")
    result = migrated.load_settings()
    migrated.close()
    assert result.prefix == expected_prefix
    assert result.next_index == 42
    assert result.output_dir == str(tmp_path / "my-captures")
    assert result.can_cfg == "C:/can.cfg"
    assert result.nic_id == "nic-123"
    assert (legacy / "state.sqlite3").is_file()


def test_migration_does_not_overwrite_existing_new_profile(tmp_path: Path) -> None:
    legacy = tmp_path / "VILLogging"
    new = tmp_path / "AutoLog"
    old_db = Repository(legacy / "state.sqlite3")
    old_db.close()
    new_db = Repository(new / "state.sqlite3")
    new_db.load_settings()
    new_db.close()

    assert migrate_legacy_profile(legacy, new) is False
