import logging

from vil_logging.diagnostics import ui_responsiveness


def test_stall_stacks_record_once_and_resume_rearms_monitor(caplog, monkeypatch):
    now = [0]
    monkeypatch.setattr(ui_responsiveness.time, "monotonic", lambda: now[0])
    monitor = ui_responsiveness.UiResponsiveness(start=False)
    with caplog.at_level(logging.INFO, logger=ui_responsiveness.__name__):
        now[0] = 6
        monitor.check()
        monitor.check()
        assert [row.message for row in caplog.records] == ["ui.unresponsive"]
        assert any(row["thread"] == "MainThread" for row in caplog.records[0].fields["threads"])
        monitor.pulse()
        monitor.check()
        assert caplog.records[-1].message == "ui.responsive_again"
        now[0] = 12
        monitor.check()
        assert [row.message for row in caplog.records].count("ui.unresponsive") == 2
    monitor.close()
