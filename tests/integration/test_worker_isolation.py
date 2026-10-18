import threading
import time

from vil_logging.contracts.commands import FakeBehavior
from vil_logging.contracts.models import Role
from vil_logging.diagnostics.debug_log import DebugLogService
from vil_logging.workers.pool import FakeWorkerPool


def test_display_poll_is_safe_after_worker_pool_closes():
    pool = FakeWorkerPool()
    pool.close()
    assert pool.drain_packets() == []


def test_one_dead_worker_does_not_block_stop_of_other_target():
    pool = FakeWorkerPool()
    try:
        roles = (Role.CAN, Role.ETHERNET)
        pool.request(roles, "prepare", "session")
        pool.request(roles, "start", "session")
        pool._processes[Role.CAN].terminate()
        pool._processes[Role.CAN].join(timeout=2)
        results = pool.request(roles, "stop", "session")
        assert not results[Role.CAN].success
        assert results[Role.ETHERNET].success
        assert results[Role.ETHERNET].state == "stopped"
    finally:
        pool.close()


def test_late_start_reply_cannot_replace_stop_result():
    pool = FakeWorkerPool({Role.ETHERNET: FakeBehavior(start_delay=0.3)})
    cancelled = threading.Event()
    try:
        roles = (Role.ETHERNET,)
        pool.request(roles, "prepare", "session")
        cancellation_timer = threading.Timer(0.04, cancelled.set)
        cancellation_timer.start()
        try:
            started = pool.request(roles, "start", "session", cancel=cancelled)
            assert not started[Role.ETHERNET].success
            stopped = pool.request(roles, "stop", "session")
            assert stopped[Role.ETHERNET].success
            assert stopped[Role.ETHERNET].command.action == "stop"
            assert stopped[Role.ETHERNET].state == "stopped"
        finally:
            cancellation_timer.cancel()
    finally:
        pool.close()


def test_worker_failure_between_commands_keeps_original_traceback(tmp_path):
    service = DebugLogService(tmp_path)
    path = service.enable()
    # Invalid injected behavior crashes the idle loop after the successful Start reply.
    pool = FakeWorkerPool({Role.ETHERNET: FakeBehavior(fail_after="injected invalid value")})
    try:
        roles = (Role.ETHERNET,)
        assert pool.request(roles, "start", "session")[Role.ETHERNET].success
        time.sleep(0.1)
        assert not pool.request(roles, "query", "session")[Role.ETHERNET].success
    finally:
        pool.close()
        service.close()
    text = path.read_text(encoding="utf-8")
    assert "command.stale_reply" in text
    assert "Traceback" in text
    assert "TypeError" in text
