import threading

from vil_logging.exit_guard import ExitGuard


def test_second_close_forces_immediately_without_waiting_for_deadline():
    exited = threading.Event()
    reasons = []
    guard = ExitGuard(reasons.append, timeout=30, terminate=lambda _code: exited.set())
    guard.request()
    assert not exited.is_set()
    guard.request()
    assert exited.wait(1) and reasons == ["repeat_close"]
    guard.finish()


def test_cleanup_can_never_block_the_hard_exit():
    blocked, release, exited = threading.Event(), threading.Event(), threading.Event()

    def abort(_reason):
        blocked.set()
        release.wait(2)

    guard = ExitGuard(abort, timeout=.02, abort_timeout=.03, terminate=lambda _code: exited.set())
    try:
        guard.request()
        assert blocked.wait(1)
        assert exited.wait(1) and not release.is_set()
    finally:
        release.set()
        guard.finish()


def test_completed_orderly_exit_cancels_the_watchdog():
    exited = threading.Event()
    guard = ExitGuard(lambda _reason: None, timeout=.02, terminate=lambda _code: exited.set())
    guard.request()
    guard.finish()
    assert not exited.wait(.06)
