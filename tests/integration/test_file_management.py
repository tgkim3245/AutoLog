"""Real Windows file operations on generated fixtures; no vehicle/tool access."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from vil_logging.contracts.models import Role, SessionPhase
from vil_logging.storage.file_access import ExclusiveFile, observe
from vil_logging.storage.file_service import FileResultStorageError, FileService
from vil_logging.storage.naming import build_plan
from vil_logging.storage.repository import Repository, RepositoryError


def seed(repository, output, roles=tuple(Role), file_format="pcapng"):
    settings = repository.load_settings(str(output))
    settings = repository.save_settings(replace(settings, ethernet_format=file_format), roles)
    plan = build_plan(settings, roles)
    repository.reserve(plan)
    for file in plan.files:
        file.final_path.write_bytes(b"Generated file-management fixture " + file.role.value.encode())
        fingerprint = observe(file.final_path)
        repository.update_capture_file(plan.session_id, file.role, "published",
                                       actual_path=str(file.final_path), inspection=fingerprint)
    repository.update_session(plan.session_id, SessionPhase.COMPLETED)
    return plan


@pytest.fixture
def captures(tmp_path):
    output = tmp_path / "captures"
    output.mkdir()
    repository = Repository(tmp_path / "state.sqlite3")
    plan = seed(repository, output)
    yield repository, FileService(repository), plan
    repository.close()


def test_rename_group_uses_literal_name_without_index_and_preserves_diag_extension(captures):
    repo, service, plan = captures
    before = repo.load_settings()
    result = service.rename_previous(plan.session_id, "한글 test")
    assert result["status"] == "completed"
    files = service.history()[0]["files"]
    assert {file["path"].rsplit("\\", 1)[-1] for file in files} == {
        "한글 test.blf", "한글 test_Diag.blf", "한글 test.pcapng"}
    assert all(file["manageable"] for file in files)
    assert repo.load_settings() == before
    assert not any(file.final_path.exists() for file in plan.files)
    assert service.history()[0]["current_name"] == "한글 test"


@pytest.mark.parametrize("problem", ["missing", "locked", "collision", "changed"])
def test_rename_group_preflight_prevents_all_changes(captures, problem):
    repo, service, plan = captures
    first = plan.files[0].final_path
    held = None
    if problem == "missing":
        first.unlink()
    elif problem == "locked":
        held = first.open("rb")
    elif problem == "collision":
        first.with_name("new.blf").write_bytes(b"existing")
    else:
        first.write_bytes(b"changed externally")
    try:
        with pytest.raises((OSError, ValueError, RuntimeError)):
            service.rename_previous(plan.session_id, "new")
        assert all(file.final_path.exists() for file in plan.files[1:])
        assert not repo.file_operations()
    finally:
        if held:
            held.close()


def test_late_rename_collision_is_preserved_and_other_results_are_recorded(captures, monkeypatch):
    repo, service, plan = captures
    original = ExclusiveFile.rename
    injected = []

    def race(handle, destination):
        if not injected:
            injected.append(destination)
            destination.write_bytes(b"late foreign file")
        original(handle, destination)

    monkeypatch.setattr(ExclusiveFile, "rename", race)
    result = service.rename_previous(plan.session_id, "new")
    assert result["status"] == "partial"
    assert injected[0].read_bytes() == b"late foreign file"
    assert [item["status"] for item in result["items"]].count("failed") == 1
    assert sum(file.final_path.exists() for file in plan.files) == 1
    assert all(file["manageable"] for file in service.history()[0]["files"])
    assert repo.load_settings().next_index == 2


def test_delete_selected_keeps_other_files_and_next_index(captures):
    repo, service, plan = captures
    selected = [service.history()[0]["files"][1]]
    result = service.delete_selected(selected)
    assert result["status"] == "completed"
    assert len([file for file in service.history()[0]["files"] if file["status"] == "deleted"]) == 1
    assert sum(file.final_path.exists() for file in plan.files) == 2
    assert not service.history()[0]["can_rename"]
    assert repo.load_settings().next_index == 2


def test_delete_partial_access_failure_preserves_used_file(captures):
    _, service, plan = captures
    selected = service.history()[0]["files"]
    with plan.files[0].final_path.open("rb"):
        result = service.delete_selected(selected)
    assert result["status"] == "partial"
    assert plan.files[0].final_path.is_file()
    assert sum(file.final_path.exists() for file in plan.files) == 1
    assert {item["status"] for item in result["items"]} == {"deleted", "failed"}


def test_changed_selection_after_confirmation_is_rejected(captures):
    repo, service, plan = captures
    selection = service.history()[0]["files"]
    service.rename_previous(plan.session_id, "changed")
    with pytest.raises(RuntimeError, match="confirmed selection"):
        service.delete_selected(selection)
    assert all(file["manageable"] for file in service.history()[0]["files"])
    assert len(repo.file_operations()) == 1


def test_unconfirmed_capture_cannot_be_managed(captures):
    _, service, plan = captures
    service.repo.update_session(plan.session_id, SessionPhase.INCOMPLETE)
    assert not any(file["manageable"] for file in service.history()[0]["files"])
    with pytest.raises(RuntimeError):
        service.rename_previous(plan.session_id, "bad")
    with pytest.raises(RuntimeError):
        service.delete_selected(service.history()[0]["files"])


def test_intent_commit_failure_cannot_mutate_a_file(captures):
    repo, service, plan = captures
    repo._connection.execute("CREATE TRIGGER reject_intent BEFORE INSERT ON file_operations "
                             "BEGIN SELECT RAISE(ABORT, 'injected intent failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        service.rename_previous(plan.session_id, "bad")
    assert all(file.final_path.exists() for file in plan.files)
    assert not repo.file_operations()


def test_rename_result_commit_failure_recovers_identity_without_repeating_work(captures, monkeypatch):
    repo, service, plan = captures
    real_commit = repo.record_file_operation
    monkeypatch.setattr(repo, "record_file_operation", lambda *args: (_ for _ in ()).throw(OSError("injected result failure")))
    with pytest.raises(FileResultStorageError):
        service.rename_previous(plan.session_id, "new")
    assert sum(file.final_path.exists() for file in plan.files) == 2
    monkeypatch.setattr(repo, "record_file_operation", real_commit)
    recovered = service.recover()
    assert recovered[0]["status"] == "partial"
    assert {item["status"] for item in recovered[0]["document"]["items"]} == {"recovered_rename", "not_applied"}
    assert all(file["manageable"] for file in service.history()[0]["files"])
    assert sum(file.final_path.exists() for file in plan.files) == 2
    assert repo.load_settings().next_index == 2


def test_missing_delete_result_is_reviewed_without_claiming_success_or_deleting_replacement(captures, monkeypatch):
    repo, service, _ = captures
    selection = [service.history()[0]["files"][0]]
    real_commit = repo.record_file_operation
    monkeypatch.setattr(repo, "record_file_operation", lambda *args: (_ for _ in ()).throw(OSError("injected")))
    with pytest.raises(FileResultStorageError):
        service.delete_selected(selection)
    monkeypatch.setattr(repo, "record_file_operation", real_commit)
    recovery = service.recover()
    assert recovery[0]["status"] == "review"
    assert service.history()[0]["files"][0]["status"] == "review"
    with pytest.raises(RepositoryError, match="Unresolved"):
        repo.check_file_claims([selection[0]["path"]])
    from pathlib import Path
    replacement = Path(selection[0]["path"])
    replacement.write_bytes(b"foreign replacement")
    service.recover()
    assert replacement.read_bytes() == b"foreign replacement"


def test_reopen_restores_actual_renamed_paths_without_consuming_numbers(captures):
    repo, service, plan = captures
    service.rename_previous(plan.session_id, "persist")
    repo.close()
    reopened = Repository(repo.db_path)
    try:
        assert not reopened.recover_incomplete()
        assert not FileService(reopened).recover()
        assert all(Path(file["path"]).stem in {"persist", "persist_Diag"}
                   for file in FileService(reopened).history()[0]["files"])
        assert reopened.load_settings().next_index == 2
    finally:
        reopened.close()


def test_schema_v1_migration_creates_verified_backup_and_preserves_next_index(tmp_path):
    path = tmp_path / "state.sqlite3"
    old = Repository(path)
    old.load_settings(str(tmp_path))
    old._connection.execute("DROP TABLE file_operations")
    old._connection.execute("PRAGMA user_version=1")
    old.close()
    migrated = Repository(path)
    try:
        assert migrated.load_settings().next_index == 1
        assert migrated._connection.execute("PRAGMA user_version").fetchone()[0] == 2
        backups = list(tmp_path.glob("*.bak"))
        assert len(backups) == 1
        with sqlite3.connect(backups[0]) as backup:
            assert backup.execute("PRAGMA user_version").fetchone()[0] == 1
            assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        migrated.close()


def test_schema_migration_failure_leaves_original_v1_usable(tmp_path, monkeypatch):
    path = tmp_path / "state.sqlite3"
    old = Repository(path)
    old.load_settings(str(tmp_path))
    old._connection.execute("DROP TABLE file_operations")
    old._connection.execute("PRAGMA user_version=1")
    old.close()
    monkeypatch.setattr(Repository, "_create_file_operations", lambda *_: (_ for _ in ()).throw(OSError("migration failure")))
    with pytest.raises(OSError, match="migration failure"):
        Repository(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute("SELECT next_index FROM settings").fetchone()[0] == "1"
