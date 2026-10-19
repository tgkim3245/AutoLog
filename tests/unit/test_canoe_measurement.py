from types import SimpleNamespace

import pytest

from vil_logging.diagnostics.canoe_measurement import measurement_diagnostics
from vil_logging.diagnostics.canoe_readiness import option_history_text, stage_guidance


def write_app(text):
    return SimpleNamespace(UI=SimpleNamespace(Write=SimpleNamespace(Text=text)))


def test_option_history_reads_only_last_error_group_and_excludes_arbitrary_output():
    app = write_app("""[E] [System] Required bus system options:
[E] [System] LIN (missing)
[E] [System] Measurement was halted.
[E] [System] Required bus system options:
[E] [System] CAN (available)
[E] [System] Ethernet (missing)
[E] [System] Measurement was halted.
[*] [System] License info has been updated.
[*] [CAPL] secret vehicle frame
[E] [System] secret vehicle frame
""")
    report = measurement_diagnostics(app, False)
    assert report["status"] == "read"
    assert report["missing_options"] == ["Ethernet"]
    assert not report["current_license_verified"]
    assert "secret" not in str(report) and "LIN" not in str(report)
    assert app.UI.Write.Text.endswith("[E] [System] secret vehicle frame\n")
    for language in ("ko", "en", "zh"):
        assert "Ethernet" in option_history_text(report, language)
        assert "F9" in stage_guidance("measurement_waiting", language)


def test_running_measurement_does_not_read_or_reuse_stale_history():
    class Forbidden:
        @property
        def UI(self):
            pytest.fail("Running measurement must not read old license errors")
    report = measurement_diagnostics(Forbidden(), True)
    assert report["missing_options"] == []
    assert report["status"] == "not_read_while_measurement_running"


@pytest.mark.parametrize("app", [SimpleNamespace(), write_app(None), write_app(123)])
def test_unavailable_history_is_nonfatal_and_never_claims_license_state(app):
    report = measurement_diagnostics(app, False)
    assert report["status"] == "unavailable" and report["missing_options"] == []
    assert not report["current_license_verified"]


def test_history_without_error_group_does_not_infer_license_and_is_bounded():
    report = measurement_diagnostics(write_app("[E] [System] Ethernet (missing)"), False)
    assert not report["missing_options"]
    text = "[E] [System] Required bus system options:\n[E] [System] Ethernet (missing)\n" + "x" * 20000
    assert not measurement_diagnostics(write_app(text), False)["missing_options"]
