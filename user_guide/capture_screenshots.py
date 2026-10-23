"""Capture current Qt widgets with illustrative data; never connects tools/devices.

Run with the project interpreter. Review all output before committing it.
"""

import hashlib
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QPoint, QRect  # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from vil_logging import __version__  # noqa: E402
from vil_logging.contracts.models import (  # noqa: E402
    AppEvent,
    AppSettings,
    ConnectionState,
    ObservationState,
    RecordingState,
    Role,
    SessionPhase,
    TargetSnapshot,
)
from vil_logging.monitors.rules import default_rules_json, parse_rules  # noqa: E402
from vil_logging.ui.i18n import tr  # noqa: E402
from vil_logging.ui.main_window import MainWindow  # noqa: E402
from vil_logging.ui.theme import apply_theme  # noqa: E402


def capture(app, language, records):
    images = Path(__file__).parent / "images"
    images.mkdir(exist_ok=True)

    def save(name, widget, rect=None):
        app.processEvents()
        pixmap = widget.grab(rect) if rect is not None else widget.grab()
        path = images / (name + ("" if language == "ko" else "-" + language) + ".png")
        assert pixmap.save(str(path))
        records.append({"file": path.name, "width": pixmap.width(), "height": pixmap.height(),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})

    window = MainWindow()
    window.resize(480, 660)
    settings = AppSettings(language=language, prefix="Drive", output_dir="C:/Logs", next_index=1,
                           can_cfg="C:/Project/CAN.cfg", diag_cfg="C:/Project/Diag.cfg",
                           can_logging_block="1", diag_logging_block="1", nic_id="example-ethernet",
                           tshark_path="C:/One Click Log/tools/Wireshark/tshark.exe")
    window.set_settings(replace(settings, can_cfg="", can_logging_block="", diag_cfg="", diag_logging_block="", nic_id=""))
    window.set_debug_status("developer_logs/One_Click_Log_developer.jsonl")
    window.show()
    app.processEvents()
    # Actual widgets with example values. No Runtime, worker pool or COM object.
    save("overview", window, QRect(0, 0, 480, window.logging_button.mapTo(window, QPoint()).y() + 60))
    window.set_settings(settings)
    dialog = window.settings_dialog
    dialog.resize(700, 730)
    dialog.show()
    app.processEvents()
    discovery = {"tshark": {"status": "ready", "version": "TShark (Wireshark) 4.6.9"},
                 "npcap": {"status": "ready", "message_ko": "Npcap 드라이버를 확인했습니다.", "message_en": "Npcap driver found.", "message_zh": "已找到 Npcap 驱动程序。"},
                 "interfaces": [
                     {"id": "example-ethernet", "name": {"ko": "이더넷", "en": "Ethernet", "zh": "以太网"}[language], "description": {"ko": "장비 연결 어댑터", "en": "Equipment adapter", "zh": "设备适配器"}[language], "status": "up", "capture_available": True},
                     {"id": "example-wifi", "name": "Wi-Fi", "description": {"ko": "무선 네트워크", "en": "Wireless network", "zh": "无线网络"}[language], "status": "up", "capture_available": True}]}
    dialog.set_connection_discovery(discovery)
    dialog.tabs.setCurrentIndex(0)
    app.processEvents()
    bottom = dialog.apply_button.mapTo(dialog, QPoint(0, dialog.apply_button.height())).y() + 18
    save("storage", dialog, QRect(14, 96, dialog.width() - 28, bottom - 96))
    for role in (Role.CAN, Role.DIAG):
        dialog.set_preparation_report({"role": role.value, "status": "attention", "readiness_stage": "measurement_waiting",
            "connected_cfg": getattr(settings, role.value + "_cfg"), "selected_block": "1",
            "blocks": [{"id": "1", "name": "CAN_Logging" if role == Role.CAN else "Logging", "format": "blf", "compatible": True}],
            "next_action_ko": "이 CANoe 창에서 채널 매핑을 확인하고 F9 → Trace 수신을 확인하세요.",
            "next_action_en": "Check channel mapping, then F9 and Trace in this CANoe window.",
            "next_action_zh": "在此 CANoe 窗口检查通道映射，然后确认 F9 和 Trace 接收。"})
    dialog.tabs.setCurrentIndex(1)
    app.processEvents()
    save("can", dialog._preparation_cards[Role.CAN])
    save("diag", dialog._preparation_cards[Role.DIAG])
    dialog.tabs.setCurrentIndex(2)
    # Keep screenshots deterministic; no host NIC statistics or external inventory.
    dialog.nic_input.set_sampling(False)
    dialog.set_connection_discovery(discovery)
    dialog.set_preparation_report({"role": "ethernet", "status": "ready",
        "message_ko": "선택한 이더넷의 캡처 준비를 확인했습니다.", "next_action_ko": "설정을 닫고 기록 시작을 누르세요.",
        "message_en": "The selected Ethernet adapter is ready.", "next_action_en": "Close settings and start recording.",
        "message_zh": "所选以太网适配器已就绪。", "next_action_zh": "关闭设置并开始记录。"})
    app.processEvents()
    save("ethernet", dialog, QRect(14, 96, dialog.width() - 28, dialog.height() - 160))
    dialog.nic_input._activity = {
        "example-ethernet": {"pps": 18500, "history": [15000, 16500, 18000, 17000, 19000, 18500] * 4},
        "example-wifi": {"pps": 24, "history": [5, 0, 10, 8, 2, 24] * 4}}
    dialog.nic_input.refresh_activity()
    dialog.nic_input.showPopup()
    app.processEvents()
    save("networks", dialog.nic_input.view().window())
    dialog.nic_input.hidePopup()
    dialog.tabs.setCurrentIndex(3)
    app.processEvents()
    save("validation", dialog.validation_panel)
    dialog.hide()

    for role in (Role.CAN, Role.ETHERNET):
        window.set_target(TargetSnapshot(role, connection=ConnectionState.READY))
    window.set_phase(SessionPhase.IDLE)
    save("ready", window, QRect(0, 0, 480, window.logging_button.mapTo(window, QPoint()).y() + 60))
    window.set_target(TargetSnapshot(Role.CAN, connection=ConnectionState.UNKNOWN))
    window.set_preparation_report({"role": "can", "status": "attention", "readiness_stage": "measurement_waiting",
        "connected_cfg": settings.can_cfg, "selected_block": "1"})
    save("measurement-waiting", window, QRect(0, 0, 480, window.logging_button.mapTo(window, QPoint()).y() + 60))
    for role in (Role.CAN, Role.ETHERNET):
        window.set_target(TargetSnapshot(role, connection=ConnectionState.READY, recording=RecordingState.RECORDING,
            observation=ObservationState.NORMAL if role == Role.ETHERNET else ObservationState.UNSUPPORTED))
    window.set_phase(SessionPhase.RECORDING)
    window.set_files(["C:/Logs/Drive_1.blf", "C:/Logs/Drive_1.pcap"], "recording")
    save("recording", window, QRect(0, 0, 480, window.logging_button.mapTo(window, QPoint()).y() + 60))
    window.set_settings(replace(settings, next_index=2))
    for role in (Role.CAN, Role.ETHERNET):
        window.set_target(TargetSnapshot(role, connection=ConnectionState.READY, recording=RecordingState.STOPPED))
    window.set_capture_history([{"session_id": "guide", "current_name": "Drive", "can_rename": True,
                                "files": [{"role": "can", "path": "C:/Logs/Drive_1.blf"}]}])
    window.set_phase(SessionPhase.COMPLETED)
    window.set_files(["C:/Logs/Drive_1.blf", "C:/Logs/Drive_1.pcap"])
    window.add_event(AppEvent("SESSION_COMPLETED", timestamp="2026-10-23T01:00:00Z"))
    bottom = window.rename_button.mapTo(window, QPoint(0, window.rename_button.height())).y() + 24
    save("completed", window, QRect(0, 0, 480, bottom))
    message = QMessageBox(QMessageBox.Icon.Information, tr("bug_report", language), tr("bug_report_saved", language).format(
        filename="One_Click_Log_BugReport_To_Taegon.Kim_20261023_100000.zip"), QMessageBox.StandardButton.Ok)
    apply_theme(message)
    message.show()
    app.processEvents()
    save("bug-report", message)
    message.close()
    rule = parse_rules(default_rules_json())[0]
    window.show_validation_failure({"session_id": "guide-popup", "rules": [rule.__dict__]})
    app.processEvents()
    save("validation-popup", window._validation_alerts[0])
    for alert in window._validation_alerts[:]:
        alert.close()
    window.hide()
    window.deleteLater()
    app.processEvents()
    return 0


def main():
    app = QApplication([])
    app.setStyle("Fusion")
    for font in ("malgun.ttf", "malgunbd.ttf", "segoeui.ttf", "msyh.ttc"):
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/" + font)
    app.setFont(QFont("Malgun Gothic", 9))
    records = []
    for language in ("ko", "en", "zh"):
        capture(app, language, records)
    images = Path(__file__).parent / "images"
    (images / "manifest.json").write_text(json.dumps({"app_version": __version__, "illustrative_data": True,
        "real_device_capture": False, "screenshots": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"screenshots": len(records), "app_version": __version__}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
