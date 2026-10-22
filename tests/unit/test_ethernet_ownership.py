"""A TShark exit alone cannot hide a remaining owned dumpcap process."""

import os
from types import SimpleNamespace

import pytest

from vil_logging.contracts.commands import Command, CommandResult
from vil_logging.contracts.models import Role
from vil_logging.workers import ethernet_pool
from vil_logging.workers.pool import FakeWorkerPool


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object accounting")
@pytest.mark.parametrize("active", [1, 2])
@pytest.mark.parametrize("state", ["stopped", "idle", "ready"])
def test_stop_requires_only_the_worker_to_remain_in_its_job(monkeypatch, active, state):
    import win32job
    pool = object.__new__(ethernet_pool.EthernetWorkerPool)
    pool._jobs = {Role.ETHERNET: "owned-test-job"}
    command = Command("stop", Role.ETHERNET, "session")
    reply = CommandResult(command, True, state, "No recorder reported")
    monkeypatch.setattr(FakeWorkerPool, "request", lambda *args, **kwargs: {Role.ETHERNET: reply})
    monkeypatch.setattr(win32job, "QueryInformationJobObject", lambda *_: {"ActiveProcesses": active})
    ticks = iter([0, 3])
    monkeypatch.setattr(ethernet_pool, "time", SimpleNamespace(monotonic=lambda: next(ticks), sleep=lambda _: None))
    result = pool.request((Role.ETHERNET,), "stop", "session")[Role.ETHERNET]
    assert result.details["active_owned_processes"] == active
    assert result.success == (active == 1)
    assert result.state == (state if active == 1 else "unknown")


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object termination")
@pytest.mark.parametrize("invalid_job", [False, True])
def test_force_abort_kills_only_owned_jobs_and_workers_even_if_job_is_gone(monkeypatch, invalid_job):
    import win32job
    pool = object.__new__(ethernet_pool.CaptureWorkerPool)
    pool._jobs = {Role.ETHERNET: "owned-job"}
    pool._processes = {}
    calls = []

    def terminate(job, code):
        calls.append((job, code))
        if invalid_job:
            raise RuntimeError("already closed")

    monkeypatch.setattr(win32job, "TerminateJobObject", terminate)
    pool.force_abort()
    assert calls == [("owned-job", 1)] and pool._closed


@pytest.mark.parametrize("already_aborted", [True, False])
def test_close_ends_owned_processes_without_waiting_for_com_or_recovery(already_aborted):
    pool = object.__new__(ethernet_pool.CaptureWorkerPool)
    pool._closed = already_aborted
    calls, sent, closed = [], [], []
    pool._jobs = {}
    pool._owned_canoe = SimpleNamespace(terminate=lambda: closed.append("owned_canoe"))
    pool._processes = {Role.DIAG: SimpleNamespace(join=lambda **_: None, is_alive=lambda: False,
                                               close=lambda: closed.append("worker"))}
    pool._pipes = {Role.DIAG: SimpleNamespace(send=sent.append, close=lambda: closed.append("pipe"))}
    pool._display = SimpleNamespace(close=lambda: closed.append("display"))
    pool._packets = SimpleNamespace(cancel_join_thread=lambda: None, close=lambda: closed.append("queue"))

    pool.request = lambda *args, **kwargs: calls.append(args)
    pool.close()
    assert pool._closed and not calls and not sent
    assert "owned_canoe" in closed and "worker" in closed and "queue" in closed
    before = list(closed)
    pool.close()
    assert closed == before


def test_display_bridge_drops_are_included_once_in_ethernet_quality(monkeypatch):
    pool = object.__new__(ethernet_pool.CaptureWorkerPool)
    pool._jobs = {}
    pool._display = SimpleNamespace(dropped=lambda session: 3 if session == "s1" else 0)
    reply = CommandResult(Command("query", Role.ETHERNET, "s1"), True, "recording", details={
        "session_id": "s1", "summary_drops": 2})
    monkeypatch.setattr(FakeWorkerPool, "request", lambda *args, **kwargs: {Role.ETHERNET: reply})
    for _ in range(2):
        observed = pool.request((Role.ETHERNET,), "query", "s1")[Role.ETHERNET].details
        assert observed["summary_drops"] == 5 and observed["display_transport_drops"] == 3
    assert reply.details["summary_drops"] == 2
