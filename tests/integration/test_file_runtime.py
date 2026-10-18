import threading
from pathlib import Path

from vil_logging.contracts.models import Role, SessionPhase
from vil_logging.runtime import Runtime
from vil_logging.storage.file_access import observe
from vil_logging.storage.naming import build_plan


def prepare(runtime):
    repo = runtime._repo
    plan = build_plan(runtime._settings, (Role.ETHERNET,))
    runtime._settings = repo.reserve(plan)
    for file in plan.files:
        file.final_path.write_bytes(b"generated runtime fixture")
        repo.update_capture_file(plan.session_id, file.role, "published",
                                 actual_path=str(file.final_path), inspection=observe(file.final_path))
    repo.update_session(plan.session_id, SessionPhase.COMPLETED)
    return plan


def test_file_operation_prevents_concurrent_capture_start_and_updates_history(tmp_path, monkeypatch):
    runtime = Runtime(tmp_path)
    release, entered = threading.Event(), threading.Event()
    try:
        runtime.initialize().result(timeout=5)
        plan = runtime._submit(prepare, runtime).result(timeout=5)
        original = runtime._file_service.rename_previous

        def delayed(*args):
            entered.set()
            assert release.wait(5)
            return original(*args)

        monkeypatch.setattr(runtime._file_service, "rename_previous", delayed)
        operation = runtime.rename_previous(plan.session_id, "changed")
        assert entered.wait(5)
        assert runtime.toggle((Role.ETHERNET,)) is None
        assert runtime.delete_files([]) is None
        release.set()
        assert operation.result(timeout=5)["status"] == "completed"
        assert runtime._settings.next_index == 2
        history = runtime.refresh_file_history().result(timeout=5)
        assert Path(history[0]["files"][0]["path"]).name == "changed.pcap"
    finally:
        release.set()
        runtime.close_for_test()


def test_runtime_restart_returns_actual_previous_paths(tmp_path):
    first = Runtime(tmp_path)
    try:
        first.initialize().result(timeout=5)
        plan = first._submit(prepare, first).result(timeout=5)
        assert first.rename_previous(plan.session_id, "persist").result(timeout=5)["status"] == "completed"
    finally:
        first.close_for_test()
    second = Runtime(tmp_path)
    try:
        second.initialize().result(timeout=5)
        history = second.refresh_file_history().result(timeout=5)
        assert second.phase == SessionPhase.IDLE
        assert history[0]["files"][0]["path"].endswith("persist.pcap")
        assert history[0]["current_name"] == "persist"
        assert second._settings.next_index == 2
    finally:
        second.close_for_test()
