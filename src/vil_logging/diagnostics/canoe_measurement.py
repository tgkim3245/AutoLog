"""Read a bounded subset of CANoe's Write history without changing its output.

History is supporting evidence, never a current license-state API. Do not copy
arbitrary CAPL/Trace output (which can contain vehicle data) into developer logs.
"""

import re


def measurement_diagnostics(app, running):
    report = {"source": "canoe_write_history", "current_license_verified": False,
              "missing_options": [], "option_error_lines": []}
    if running:
        return {**report, "status": "not_read_while_measurement_running"}
    try:
        text = app.UI.Write.Text
        if not isinstance(text, str):
            raise ValueError("CANoe Write.Text did not return text")
        # Only the most recent options-error group in a bounded tail. Messages
        # can be old; callers must not turn this into a current license verdict.
        group, missing = [], []
        for line in text[-16384:].splitlines():
            if "[System]" not in line:
                continue
            message = line.split("[System]", 1)[1].strip()
            if message == "Required bus system options:":
                group, missing = [message], []
            elif group:
                option = re.fullmatch(r"([A-Za-z0-9 ._+/-]{1,64})\s+\((available|missing)\)", message)
                if option:
                    group.append(message)
                    if option[2] == "missing":
                        missing.append(option[1].strip())
                elif message == "Measurement was halted.":
                    group.append(message)
        return {**report, "status": "read", "missing_options": missing[:16],
                "option_error_lines": group[:18]}
    except Exception as error:
        return {**report, "status": "unavailable", "detail": str(error)[:512]}
