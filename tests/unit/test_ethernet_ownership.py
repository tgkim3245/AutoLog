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
def test_stop_requires_only_the_worker_to_remain_in_its_job(monkeypatch, active):
    import win32job
    pool = object.__new__(ethernet_pool.EthernetWorkerPool)
    pool._jobs = {Role.ETHERNET: "owned-test-job"}
    command = Command("stop", Role.ETHERNET, "session")
    reply = CommandResult(command, True, "stopped", "TShark exited")
    monkeypatch.setattr(FakeWorkerPool, "request", lambda *args, **kwargs: {Role.ETHERNET: reply})
    monkeypatch.setattr(win32job, "QueryInformationJobObject", lambda *_: {"ActiveProcesses": active})
    ticks = iter([0, 3])
    monkeypatch.setattr(ethernet_pool, "time", SimpleNamespace(monotonic=lambda: next(ticks), sleep=lambda _: None))
    result = pool.request((Role.ETHERNET,), "stop", "session")[Role.ETHERNET]
    assert result.details["active_owned_processes"] == active
    assert result.success == (active == 1)
    assert result.state == ("stopped" if active == 1 else "unknown")
