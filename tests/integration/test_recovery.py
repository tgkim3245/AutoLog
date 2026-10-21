"""Generated captures and native Windows handles; no CANoe or NIC access."""

import struct
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from vil_logging.contracts.models import Role, SessionPhase
from vil_logging.runtime import Runtime
from vil_logging.storage.blf import FILE_HEADER
from vil_logging.storage.file_access import ExclusiveFile, observe
from vil_logging.storage.file_service import FileResultStorageError, FileService
from vil_logging.storage.naming import build_plan
from vil_logging.storage.recovery import RecoveryService
from vil_logging.storage.repository import Repository, RepositoryError


def empty_blf():
    return FILE_HEADER.pack(b"LOGG", 144, *([0] * 8), 144, 144, 0, 0, *([0] * 16)).ljust(144, b"\0")


def seed(repo, output, roles=(Role.CAN,)):
    settings = repo.load_settings(str(output))
    settings = repo.save_settings(replace(settings, output_dir=str(output)), roles)
    plan = build_plan(settings, roles)
    repo.reserve(plan)
    for file in plan.files:
        file.temp_path.parent.mkdir(parents=True, exist_ok=True)
        file.temp_path.write_bytes(empty_blf())
    repo.update_session(plan.session_id, SessionPhase.INCOMPLETE)
    return plan


@pytest.fixture
def recovery(tmp_path):
    output = tmp_path / "captures"
    output.mkdir()
    repo = Repository(tmp_path / "state.sqlite3")
    plan = seed(repo, output)
    yield repo, RecoveryService(repo), plan
    repo.close()


def selected(service, plan):
    return next(row for row in service.report()["sessions"] if row["session_id"] == plan.session_id)


def test_publish_valid_file_then_finish_never_marks_acquisition_success(recovery):
    repo, service, plan = recovery
    file = plan.files[0]
    content = file.temp_path.read_bytes()
    result = service.publish(plan.session_id, "can", selected(service, plan)["token"], True)
    assert result["inspection"]["object_count"] == 0
    assert result["inspection"]["recovery_validation"] == "structural_read_only"
    assert file.final_path.read_bytes() == content
    assert not file.temp_path.parent.exists()
    assert repo.captures()[0]["phase"] == "incomplete"
    service.finish_session(plan.session_id, selected(service, plan)["token"], True)
    assert not service.report()["sessions"]
    assert repo.captures()[0]["phase"] == "failed"
    assert repo.load_settings().next_index == 2
    assert FileService(repo).history()[0]["files"][0]["manageable"]


@pytest.mark.parametrize("already_moved", [False, True])
def test_interrupted_sealed_blf_publication_reconciles_without_overwrite(recovery, already_moved):
    from vil_logging.storage.blf_snapshot import seal_blf
    from vil_logging.storage.capture_files import publish_capture

    repo, service, plan = recovery
    file = plan.files[0]
    content = file.temp_path.read_bytes()
    inspection = seal_blf(file.temp_path)
    repo.update_capture_file(plan.session_id, Role.CAN, "publishing", inspection=inspection)
    if already_moved:
        publish_capture(file, inspection)
    service.publish(plan.session_id, "can", selected(service, plan)["token"], True)
    assert file.final_path.read_bytes() == content
    assert not file.temp_path.exists() and not file.temp_path.parent.exists()
    service.finish_session(plan.session_id, selected(service, plan)["token"], True)
    assert not service.report()["sessions"]


def test_recovery_keeps_finalization_file_ownership_from_interrupted_stop(recovery):
    from uuid import uuid4

    repo, service, plan = recovery
    file = plan.files[0]
    helper = file.temp_path.parent / (".AutoLog_finalize_" + uuid4().hex + ".blf")
    helper.write_bytes(b"disposable output from a stopped owned trigger")
    repo.update_capture_file(plan.session_id, Role.CAN, "unknown", stop_evidence={
        "finalization_files": [{"path": str(helper), "identity": observe(helper),
                                "start_attempted": True, "stopped": True}]})
    row = selected(service, plan)
    assert str(helper) in [candidate["path"] for candidate in row["files"][0]["candidates"]]
    result = service.publish(plan.session_id, "can", row["token"], True)
    assert result["inspection"]["finalization_files"][0]["cleaned"]
    assert file.final_path.exists() and not helper.exists() and not file.temp_path.parent.exists()
    service.finish_session(plan.session_id, selected(service, plan)["token"], True)
    assert not service.report()["sessions"]


@pytest.mark.parametrize("fault", ["damaged", "used", "collision", "link", "missing"])
def test_unreadable_used_ambiguous_files_are_preserved(recovery, fault):
    repo, service, plan = recovery
    file = plan.files[0]
    handle = None
    if fault == "damaged":
        file.temp_path.write_bytes(b"LOGG damaged")
    elif fault == "used":
        handle = file.temp_path.open("rb")
    elif fault == "collision":
        file.final_path.write_bytes(b"foreign existing output")
    elif fault == "link":
        file.final_path.hardlink_to(file.temp_path)
    else:
        file.temp_path.unlink()
    before = {path: path.read_bytes() for path in (file.temp_path, file.final_path) if path.exists()}
    try:
        with pytest.raises((OSError, ValueError, RuntimeError)):
            service.publish(plan.session_id, "can", selected(service, plan)["token"], True)
    finally:
        if handle:
            handle.close()
    assert {path: path.read_bytes() for path in before} == before
    assert repo.load_settings().next_index == 2
    assert repo.captures()[0]["phase"] == "incomplete"


@pytest.mark.parametrize("action", ["publish", "finish"])
def test_confirmation_and_fresh_evidence_are_required(recovery, action):
    _, service, plan = recovery
    token = selected(service, plan)["token"]
    invoke = (lambda stopped: service.publish(plan.session_id, "can", token, stopped)) if action == "publish" else (
        lambda stopped: service.finish_session(plan.session_id, token, stopped))
    with pytest.raises(RuntimeError, match="Confirm"):
        invoke(False)
    plan.files[0].temp_path.write_bytes(b"changed after review")
    with pytest.raises(RuntimeError, match="selection changed"):
        invoke(True)


def test_finish_keeps_damaged_files_and_records_failure_without_deleting_work_directory(recovery):
    repo, service, plan = recovery
    file = plan.files[0]
    file.temp_path.write_bytes(b"damaged data to keep")
    service.finish_session(plan.session_id, selected(service, plan)["token"], True)
    assert file.temp_path.read_bytes() == b"damaged data to keep"
    assert not service.report()["sessions"]
    assert repo.captures()[0]["files"][0]["state"] == "retained"
    assert FileService(repo).history()[0]["files"][0]["path"] == str(file.temp_path)
    assert not FileService(repo).history()[0]["files"][0]["manageable"]


def test_finish_refuses_a_file_that_is_still_open(recovery):
    _, service, plan = recovery
    with plan.files[0].temp_path.open("rb"), pytest.raises(OSError):
        service.finish_session(plan.session_id, selected(service, plan)["token"], True)
    assert selected(service, plan)["phase"] == "incomplete"


def test_late_destination_collision_is_never_replaced(recovery, monkeypatch):
    _, service, plan = recovery
    original = ExclusiveFile.move

    def collide(handle, destination):
        destination.write_bytes(b"foreign late file")
        original(handle, destination)

    monkeypatch.setattr(ExclusiveFile, "move", collide)
    with pytest.raises(OSError):
        service.publish(plan.session_id, "can", selected(service, plan)["token"], True)
    assert plan.files[0].final_path.read_bytes() == b"foreign late file"
    assert plan.files[0].temp_path.read_bytes() == empty_blf()


def test_durable_intent_failure_cannot_move_a_file(recovery, monkeypatch):
    repo, service, plan = recovery

    def fail(*args):
        raise RepositoryError("injected intent failure")

    monkeypatch.setattr(repo, "begin_file_operation", fail)
    with pytest.raises(RepositoryError):
        service.publish(plan.session_id, "can", selected(service, plan)["token"], True)
    assert plan.files[0].temp_path.exists() and not plan.files[0].final_path.exists()


def test_move_followed_by_result_storage_failure_reconciles_exact_identity(recovery, monkeypatch):
    repo, service, plan = recovery
    original = repo.record_file_operation

    def fail(*args):
        raise RepositoryError("injected result failure")

    monkeypatch.setattr(repo, "record_file_operation", fail)
    with pytest.raises(FileResultStorageError):
        service.publish(plan.session_id, "can", selected(service, plan)["token"], True)
    assert plan.files[0].final_path.exists() and not plan.files[0].temp_path.exists()
    monkeypatch.setattr(repo, "record_file_operation", original)
    FileService(repo).recover()
    assert not service.report()["operations"]
    file = repo.captures()[0]["files"][0]
    assert file["state"] == "published" and file["metadata"]["actual_path"] == str(plan.files[0].final_path)
    assert repo.load_settings().next_index == 2


def test_original_publication_crash_requires_saved_inspection_identity(recovery):
    repo, service, plan = recovery
    file = plan.files[0]
    inspected = observe(file.temp_path)
    repo.update_capture_file(plan.session_id, Role.CAN, "publishing", inspection=inspected)
    file.temp_path.rename(file.final_path)
    service.publish(plan.session_id, "can", selected(service, plan)["token"], True)
    assert repo.captures()[0]["files"][0]["state"] == "published"


def test_uncertain_operation_acknowledgement_preserves_foreign_files_and_does_not_claim_delete(recovery):
    repo, service, plan = recovery
    file = plan.files[0]
    fingerprint = observe(file.temp_path)
    document = {"items": [{"session_id": plan.session_id, "role": "can", "source": str(file.temp_path),
                           "identity": fingerprint, "status": "review"}]}
    repo.begin_file_operation("interrupted", "delete", document)
    file.temp_path.write_bytes(b"unrelated replacement")
    FileService(repo).recover()
    operation = service.report()["operations"][0]
    with pytest.raises(RuntimeError, match="operations first"):
        service.finish_session(plan.session_id, selected(service, plan)["token"], True)
    service.acknowledge_operation("interrupted", operation["token"], True)
    assert file.temp_path.read_bytes() == b"unrelated replacement"
    assert repo.file_operations()[0]["status"] == "acknowledged"
    assert repo.captures()[0]["files"][0]["state"] == "unconfirmed"
    assert not service.report()["operations"]
    service.finish_session(plan.session_id, selected(service, plan)["token"], True)
    assert not FileService(repo).history()[0]["files"][0]["manageable"]


def test_recheck_can_resolve_previously_reviewed_operation(recovery):
    repo, service, plan = recovery
    file = plan.files[0]
    fingerprint = observe(file.temp_path)
    item = {"session_id": plan.session_id, "role": "can", "source": str(file.temp_path),
            "destination": str(file.final_path), "identity": fingerprint, "status": "review"}
    repo.begin_file_operation("interrupted", "recover_publish", {"items": [item]})
    FileService(repo).recover()
    assert repo.captures()[0]["files"][0]["state"] != "published"
    assert repo.captures()[0]["files"][0]["final_path"] == str(file.final_path)


def test_recovery_is_not_limited_to_latest_hundred_captures(recovery):
    repo, service, plan = recovery
    for _ in range(101):
        later = seed(repo, Path(plan.files[0].final_path).parent)
        repo.update_session(later.session_id, SessionPhase.COMPLETED)
    assert selected(service, plan)["session_id"] == plan.session_id


def test_restart_requires_manual_review_before_new_capture_then_allows_orderly_exit(tmp_path):
    output = tmp_path / "captures"
    output.mkdir()
    repo = Repository(tmp_path / "state.sqlite3")
    plan = seed(repo, output)
    repo.close()
    runtime = Runtime(tmp_path)
    try:
        runtime.initialize().result(5)
        assert runtime.phase == SessionPhase.INCOMPLETE
        assert runtime.toggle((Role.CAN,)) is None
        report = runtime._submit(runtime._refresh_recovery).result(5)
        row = report["sessions"][0]
        result = runtime.recover({"action": "finish", "session_id": plan.session_id,
                                  "token": row["token"], "stopped": True}).result(5)
        assert result["success"] and runtime.phase == SessionPhase.IDLE
        assert runtime._settings.next_index == 2
        assert runtime.request_exit().result(5)
        assert plan.files[0].temp_path.exists()
    finally:
        runtime.close_for_test()


def test_old_incomplete_record_does_not_trap_exit_and_remains_recoverable(tmp_path):
    output = tmp_path / "captures"
    output.mkdir()
    repo = Repository(tmp_path / "state.sqlite3")
    plan = seed(repo, output)
    before = plan.files[0].temp_path.read_bytes()
    repo.close()
    for _ in range(2):
        runtime = Runtime(tmp_path)
        try:
            runtime.initialize().result(5)
            assert runtime.phase == SessionPhase.INCOMPLETE and runtime._plan is None
            assert runtime.toggle((Role.CAN,)) is None
            report = runtime._submit(runtime._refresh_recovery).result(5)
            assert report["sessions"][0]["session_id"] == plan.session_id
            assert runtime._settings.next_index == 2
            assert runtime.request_exit().result(5) is True
            assert runtime._closed
            assert plan.files[0].temp_path.read_bytes() == before
        finally:
            runtime.close_for_test()


def test_pcap_recovery_uses_full_read_and_rejects_format_mismatch(recovery, monkeypatch):
    from vil_logging.storage import recovery as module
    repo, service, _ = recovery
    settings = repo.load_settings()
    plan = build_plan(settings, (Role.ETHERNET,))
    repo.reserve(plan)
    file = plan.files[0]
    file.temp_path.parent.mkdir(parents=True)
    file.temp_path.write_bytes(struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1))
    repo.update_session(plan.session_id, SessionPhase.INCOMPLETE)
    fake_tool = file.temp_path.parent / "capinfos.exe"
    fake_tool.touch()
    monkeypatch.setattr(module, "_tool_candidates", lambda *args, **kwargs: [fake_tool])
    calls = []

    def run(arguments, **kwargs):
        calls.append(arguments)
        return type("Result", (), {"returncode": 0, "stdout": "fixture\tpcapng\t0\n", "stderr": ""})()

    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(ValueError, match="format"):
        service.publish(plan.session_id, "ethernet", selected(service, plan)["token"], True)
    assert calls[0][1:8] == ["-T", "-B", "-Q", "-r", "-t", "-c", str(file.temp_path)]
    assert file.temp_path.exists() and not file.final_path.exists()


def test_recovery_locks_capture_start_and_keeps_other_abandoned_sessions_blocked(tmp_path, monkeypatch):
    runtime = Runtime(tmp_path)
    release, entered = threading.Event(), threading.Event()
    try:
        runtime.initialize().result(5)
        first = runtime._submit(seed, runtime._repo, tmp_path / "captures").result(5)
        second = runtime._submit(seed, runtime._repo, tmp_path / "captures").result(5)
        runtime._submit(runtime._set_phase, SessionPhase.INCOMPLETE).result(5)
        report = runtime._submit(runtime._refresh_recovery).result(5)
        row = next(row for row in report["sessions"] if row["session_id"] == first.session_id)
        original = runtime._recovery.finish_session

        def delayed(*args):
            entered.set()
            assert release.wait(5)
            return original(*args)

        monkeypatch.setattr(runtime._recovery, "finish_session", delayed)
        future = runtime.recover({"action": "finish", "session_id": first.session_id,
                                  "token": row["token"], "stopped": True})
        assert entered.wait(5)
        assert runtime.toggle((Role.CAN,)) is None
        assert runtime.recover({"action": "recheck"}) is None
        release.set()
        assert future.result(5)["success"]
        assert runtime.phase == SessionPhase.INCOMPLETE
        remaining = runtime._submit(runtime._refresh_recovery).result(5)["sessions"]
        assert [row["session_id"] for row in remaining] == [second.session_id]
    finally:
        release.set()
        runtime.close_for_test()


def test_live_unconfirmed_session_cannot_be_manually_released(tmp_path):
    runtime = Runtime(tmp_path)
    try:
        runtime.initialize().result(5)
        plan = runtime._submit(seed, runtime._repo, tmp_path / "captures").result(5)
        runtime._plan = plan
        runtime._submit(runtime._set_phase, SessionPhase.INCOMPLETE).result(5)
        report = runtime._submit(runtime._refresh_recovery).result(5)
        assert report["live_session_id"] == plan.session_id
        row = report["sessions"][0]
        result = runtime.recover({"action": "finish", "session_id": plan.session_id,
                                  "token": row["token"], "stopped": True}).result(5)
        assert not result["success"]
        assert runtime.phase == SessionPhase.INCOMPLETE
    finally:
        # No real recorder has been opened by this generated reservation.
        runtime._plan = None
        runtime.close_for_test()
