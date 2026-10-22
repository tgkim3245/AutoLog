"""User-authorized interrupted-work deletion must not touch completed/foreign files."""

from pathlib import Path

import pytest
from test_recovery import seed

from vil_logging.contracts.models import Role, SessionPhase
from vil_logging.runtime import Runtime
from vil_logging.storage.discard import discard_interrupted
from vil_logging.storage.file_access import ExclusiveFile, observe
from vil_logging.storage.repository import Repository


@pytest.mark.parametrize("missing", [True, False])
def test_startup_clears_old_work_and_db_without_blocking_or_reusing_index(tmp_path, missing):
    output = tmp_path / "captures"
    output.mkdir()
    repo = Repository(tmp_path / "state.sqlite3")
    plan = seed(repo, output, (Role.CAN, Role.DIAG))
    if missing:
        for file in plan.files:
            file.temp_path.unlink()
        plan.files[0].temp_path.parent.rmdir()
    repo.close()
    runtime = Runtime(tmp_path)
    try:
        runtime.initialize().result(5)
        assert runtime.phase == SessionPhase.IDLE and runtime._settings.next_index == 2
        assert not runtime._submit(runtime._refresh_recovery).result(5)["sessions"]
        assert not any(file.temp_path.exists() for file in plan.files)
        assert runtime.request_exit().result(5)
    finally:
        runtime.close_for_test()


def test_locked_work_is_retried_without_blocking_new_capture(tmp_path):
    output = tmp_path / "captures"
    output.mkdir()
    repo = Repository(tmp_path / "state.sqlite3")
    plan = seed(repo, output)
    file = plan.files[0]
    try:
        with ExclusiveFile(file.temp_path, observe(file.temp_path)):
            report = discard_interrupted(repo, reason="restart")
            assert report[0]["pending"] and file.temp_path.exists()
            assert repo.captures()[0]["phase"] == "failed"
        assert not discard_interrupted(repo, reason="retry")[0]["pending"]
        assert not file.temp_path.exists() and repo.load_settings().next_index == 2
    finally:
        repo.close()


def test_partial_publication_and_unrelated_work_contents_are_preserved(tmp_path):
    output = tmp_path / "captures"
    output.mkdir()
    repo = Repository(tmp_path / "state.sqlite3")
    plan = seed(repo, output, (Role.CAN, Role.DIAG))
    published, interrupted = plan.files
    published.temp_path.rename(published.final_path)
    repo.update_capture_file(plan.session_id, Role.CAN, "published")
    unknown = interrupted.temp_path.parent / "user_notes.txt"
    unknown.write_text("keep")
    try:
        discard_interrupted(repo, reason="restart")
        assert published.final_path.is_file() and not interrupted.temp_path.exists()
        assert unknown.read_text() == "keep"
        assert repo.captures()[0]["files"][0]["state"] == "published"
    finally:
        repo.close()


def test_invalid_work_path_never_deletes_a_file_outside_reserved_session(tmp_path):
    output = tmp_path / "captures"
    output.mkdir()
    repo = Repository(tmp_path / "state.sqlite3")
    plan = seed(repo, output)
    external = tmp_path / "unrelated.blf"
    external.write_bytes(b"keep")
    repo._connection.execute("UPDATE capture_files SET temp_path=? WHERE session_id=?",
                             (str(external), plan.session_id))
    try:
        assert discard_interrupted(repo, reason="restart")[0]["pending"]
        assert external.read_bytes() == b"keep" and Path(plan.files[0].temp_path).exists()
        assert repo.captures()[0]["phase"] == "failed"
    finally:
        repo.close()
