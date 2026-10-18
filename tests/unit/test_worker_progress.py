"""Worker diagnostics must not be mistaken for completed capture commands."""

from collections import deque
from types import SimpleNamespace

from vil_logging.contracts.commands import CommandResult, WorkerProgress
from vil_logging.contracts.models import Role
from vil_logging.workers.pool import FakeWorkerPool


def test_progress_is_logged_while_request_waits_for_its_actual_result(monkeypatch, caplog):
    pool = FakeWorkerPool()
    replies = deque()

    def send(command):
        replies.append(WorkerProgress(command, {"event": "canoe.output_apply_requested"}, 123))
        replies.append(CommandResult(command, True, "configured", "exact path read back", 123))

    pipe = SimpleNamespace(send=send, poll=lambda: bool(replies), recv=replies.popleft)
    pool._pipes = {Role.CAN: pipe}
    pool._processes = {Role.CAN: SimpleNamespace(is_alive=lambda: True)}
    monkeypatch.setattr(pool, "_ensure", lambda role: None)
    with caplog.at_level("INFO", logger="vil_logging.workers.pool"):
        result = pool.request((Role.CAN,), "configure", "s1", params={"temp_path": "test.blf"})
    assert result[Role.CAN].state == "configured"
    assert any(record.msg == "command.progress" and record.fields["event"] == "canoe.output_apply_requested"
               for record in caplog.records)
    pool._pipes.clear()
    pool._processes.clear()
    pool.close()
