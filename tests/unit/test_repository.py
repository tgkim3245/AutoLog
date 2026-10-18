import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from vil_logging.contracts.models import AppEvent, Role, SessionPhase
from vil_logging.storage.naming import CollisionError, build_plan, validate_settings
from vil_logging.storage.repository import Repository, RepositoryError, StaleSettingsError


def open_repository(tmp_path):
    output = tmp_path / "captures"
    output.mkdir(exist_ok=True)
    repository = Repository(tmp_path / "metadata.sqlite3")
    settings = repository.load_settings(str(output))
    return repository, settings, output


def query_database(db_path, statement):
    with sqlite3.connect(db_path) as connection:
        return connection.execute(statement).fetchall()


def test_reservation_durably_preserves_exact_huge_index_after_restart(tmp_path):
    repository, settings, output = open_repository(tmp_path)
    huge_index = 10**60 + 123456789
    settings = repository.save_settings(replace(settings, next_index=huge_index), tuple(Role))
    plan = build_plan(settings, tuple(Role))
    updated = repository.reserve(plan)
    assert updated.next_index == huge_index + 1
    assert not list(output.iterdir())
    repository.close()

    restarted = Repository(tmp_path / "metadata.sqlite3")
    assert restarted.load_settings().next_index == huge_index + 1
    assert query_database(restarted.db_path, "SELECT typeof(capture_index),capture_index FROM sessions") == [
        ("text", str(huge_index)),
    ]
    assert query_database(restarted.db_path, "SELECT typeof(next_index),next_index FROM settings") == [
        ("text", str(huge_index + 1)),
    ]
    assert len(query_database(restarted.db_path, "SELECT * FROM capture_files")) == 3
    restarted.close()


def test_settings_collision_rejects_entire_edit_and_preserves_file(tmp_path):
    repository, settings, output = open_repository(tmp_path)
    existing = output / "new_123.blf"
    existing.write_bytes(b"precious existing log")
    with pytest.raises(CollisionError) as error:
        repository.save_settings(replace(settings, prefix="new_", next_index=123), (Role.CAN,))
    assert error.value.paths == [existing]
    assert repository.load_settings() == settings
    assert existing.read_bytes() == b"precious existing log"
    assert not repository.recent_events()
    repository.close()


def test_collision_appearing_after_preview_does_not_consume_index(tmp_path):
    repository, settings, output = open_repository(tmp_path)
    plan = build_plan(settings, (Role.CAN,))
    plan.files[0].final_path.write_bytes(b"another process")
    with pytest.raises(CollisionError):
        repository.reserve(plan)
    assert repository.load_settings() == settings
    assert not query_database(repository.db_path, "SELECT * FROM sessions")
    assert not (output / ".vil_work").exists()
    repository.close()


def test_database_failure_rolls_back_session_plan_event_and_number(tmp_path):
    repository, settings, _ = open_repository(tmp_path)
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute("CREATE TRIGGER fail_file_insert BEFORE INSERT ON capture_files "
                           "BEGIN SELECT RAISE(ABORT, 'injected disk metadata failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        repository.reserve(build_plan(settings, (Role.CAN,)))
    assert repository.load_settings() == settings
    assert not query_database(repository.db_path, "SELECT * FROM sessions")
    assert not query_database(repository.db_path, "SELECT * FROM capture_files")
    assert not repository.recent_events()
    repository.close()


def test_explicit_reset_allows_reusing_number_when_names_are_free(tmp_path):
    repository, settings, _ = open_repository(tmp_path)
    first_plan = build_plan(settings, (Role.CAN,), demo=True)
    settings = repository.reserve(first_plan)
    repository.update_session(first_plan.session_id, SessionPhase.COMPLETED)
    settings = repository.save_settings(replace(settings, next_index=1, prefix="other_"), (Role.CAN,))
    second_plan = build_plan(settings, (Role.CAN,), demo=True)
    settings = repository.reserve(second_plan)
    assert settings.next_index == 2
    assert query_database(repository.db_path, "SELECT capture_index FROM sessions") == [("1",), ("1",)]
    repository.close()


def test_duplicate_uuid_rolls_back_after_explicit_reset(tmp_path):
    repository, settings, _ = open_repository(tmp_path)
    plan = build_plan(settings, (Role.CAN,))
    settings = repository.reserve(plan)
    settings = repository.save_settings(replace(settings, next_index=1), (Role.CAN,))
    same_id = build_plan(settings, (Role.CAN,), session_id=plan.session_id)
    with pytest.raises(sqlite3.IntegrityError):
        repository.reserve(same_id)
    assert repository.load_settings() == settings
    assert len(query_database(repository.db_path, "SELECT * FROM sessions")) == 1
    repository.close()


def test_stale_plan_and_settings_edit_do_not_overwrite_committed_number(tmp_path):
    repository, original, _ = open_repository(tmp_path)
    stale_plan = build_plan(original, (Role.CAN,))
    changed = repository.save_settings(replace(original, prefix="latest_"), (Role.CAN,))
    with pytest.raises(StaleSettingsError):
        repository.reserve(stale_plan)
    with pytest.raises(StaleSettingsError):
        repository.save_settings(replace(original, next_index=999), (Role.CAN,))
    assert repository.load_settings() == changed
    repository.close()


def test_prefix_edits_and_session_details_do_not_change_next_index(tmp_path):
    repository, settings, _ = open_repository(tmp_path)
    plan = build_plan(settings, (Role.DIAG,))
    settings = repository.reserve(plan)
    repository.update_session(plan.session_id, SessionPhase.COMPLETED, renamed_prefix="경로_", deleted=True)
    assert repository.load_settings() == settings
    changed = repository.save_settings(replace(settings, prefix="new_"), (Role.DIAG,))
    assert changed.next_index == settings.next_index
    repository.close()


def test_tampered_plan_cannot_write_outside_committed_directory(tmp_path):
    repository, settings, _ = open_repository(tmp_path)
    plan = build_plan(settings, (Role.CAN,))
    forged_file = replace(plan.files[0], temp_path=tmp_path / "outside.blf")
    with pytest.raises(RepositoryError, match="paths or names"):
        repository.reserve(replace(plan, files=(forged_file,)))
    assert repository.load_settings() == settings
    repository.close()


def test_recovery_preserves_partial_file_and_reports_incomplete_on_later_restart(tmp_path):
    repository, settings, _ = open_repository(tmp_path)
    plan = build_plan(settings, (Role.CAN, Role.ETHERNET))
    updated = repository.reserve(plan)
    plan.files[0].temp_path.parent.mkdir(parents=True)
    plan.files[0].temp_path.write_bytes(b"unfinished capture")
    repository.update_session(plan.session_id, SessionPhase.RECORDING, evidence="recording confirmed")
    repository.close()

    restarted = Repository(tmp_path / "metadata.sqlite3")
    recovered = restarted.recover_incomplete()
    assert len(recovered) == 1
    assert recovered[0]["previous_phase"] == SessionPhase.RECORDING.value
    assert recovered[0]["phase"] == SessionPhase.INCOMPLETE.value
    assert recovered[0]["index"] == plan.index
    assert recovered[0]["files"][0]["temp_path"] == str(plan.files[0].temp_path)
    assert plan.files[0].temp_path.read_bytes() == b"unfinished capture"
    assert not plan.files[0].final_path.exists()
    assert restarted.load_settings() == updated
    assert len(restarted.recover_incomplete()) == 1
    assert [event.code for event in restarted.recent_events()].count("session.recovered_incomplete") == 1
    restarted.close()


def test_completed_and_failed_sessions_are_not_recovered(tmp_path):
    repository, settings, _ = open_repository(tmp_path)
    for phase in (SessionPhase.COMPLETED, SessionPhase.FAILED):
        plan = build_plan(settings, (Role.CAN,), demo=True)
        settings = repository.reserve(plan)
        repository.update_session(plan.session_id, phase)
    assert repository.recover_incomplete() == []
    repository.close()


def test_persistent_events_work_without_developer_log_and_return_recent_in_order(tmp_path):
    repository, _, _ = open_repository(tmp_path)
    for index in range(5):
        repository.append_event(AppEvent(f"event.{index}", original="원문 근거", params={"index": index}))
    assert [event.code for event in repository.recent_events(3)] == ["event.2", "event.3", "event.4"]
    repository.close()
    restarted = Repository(tmp_path / "metadata.sqlite3")
    assert restarted.recent_events(1)[0].original == "원문 근거"
    assert restarted.recent_events(0) == []
    restarted.close()


def test_repository_rejects_cross_thread_access(tmp_path):
    repository, _, _ = open_repository(tmp_path)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(repository.load_settings)
        with pytest.raises(RepositoryError, match="creator thread"):
            future.result()
    repository.close()


def test_unsupported_schema_preserves_database(tmp_path):
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE future_metadata (content TEXT)")
        connection.execute("INSERT INTO future_metadata VALUES('preserve me')")
        connection.execute("PRAGMA user_version=999")
    with pytest.raises(RepositoryError, match="Unsupported database schema"):
        Repository(path)
    assert query_database(path, "SELECT content FROM future_metadata") == [("preserve me",)]


def test_connection_choices_survive_restart_even_when_capture_names_collide(tmp_path):
    repository, settings, output = open_repository(tmp_path)
    (output / "AutoLog_1.blf").write_bytes(b"keep existing capture")
    first = repository.save_preferences({"can_cfg": "D:/test/car.cfg", "diag_cfg": "D:/test/diag.cfg"})
    saved = repository.save_preferences({"tshark_path": "C:/tools/tshark.exe", "nic_id": "adapter-123",
                                         "output_dir": "E:/disconnected-drive", "ethernet_format": "pcapng"})
    assert saved.next_index == settings.next_index and saved.prefix == settings.prefix
    assert saved.can_cfg == first.can_cfg and saved.diag_cfg == first.diag_cfg
    assert repository.save_preferences({"can_cfg": saved.can_cfg}) == saved  # No-op acknowledgement.
    repository.close()
    restarted = Repository(tmp_path / "metadata.sqlite3")
    assert restarted.load_settings() == saved
    with pytest.raises((ValueError, OSError)):
        validate_settings(saved, (Role.CAN,))  # Remembering a path does not bypass capture preflight.
    restarted.close()


@pytest.mark.parametrize("patch", [{"prefix": "unsafe_"}, {"language": "xx"},
                                     {"can_cfg": "bad\npath"}, {"ethernet_format": "txt"}])
def test_invalid_preference_patch_is_atomic(tmp_path, patch):
    repository, settings, _ = open_repository(tmp_path)
    with pytest.raises(RepositoryError):
        repository.save_preferences({"diag_cfg": "D:/valid.cfg", **patch})
    assert repository.load_settings() == settings
    repository.close()
