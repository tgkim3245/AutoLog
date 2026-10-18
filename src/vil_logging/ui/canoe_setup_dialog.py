"""Review and explicitly apply Vector's independent-client setting."""

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from vil_logging.diagnostics.canoe_setup import (
    canoe_process_ids,
    registered_settings_file,
    set_single_client,
    single_client_enabled,
)

from .theme import apply_theme

log = logging.getLogger(__name__)


class CanoeSetupDialog(QDialog):
    def __init__(self, language="ko", parent=None):
        super().__init__(parent)
        self.language = language
        self.path = self.expected = None
        self.applied_enabled = None
        self.setWindowTitle(self._t("CANoe cfg별 연결 설정", "CANoe per-cfg connection setup"))
        self.setMinimumSize(610, 460)
        self.resize(640, 500)
        apply_theme(self)
        layout = QVBoxLayout(self)
        guide = QLabel(self._t(
            "AutoLog는 각 대상에 선택한 .cfg 하나를 연결하고, 그 구성에서 기록 블록 하나를 제어합니다.\n"
            "예: CAN .cfg → CAN 기록 블록 / Diag .cfg → Diag 기록 블록\n\n"
            "이 설정은 CAN·Diag 두 .cfg를 함께 사용할 때 필요합니다. 두 파일은 서로 다른 CANoe 인스턴스에서 열어야 합니다. "
            "기본 COM 연결은 "
            "두 번째 요청에도 이미 열린 CANoe 창을 돌려줄 수 있어, Diag가 CAN 구성에 붙는 문제가 생깁니다. "
            "아래 설정은 AutoLog의 각 .cfg 연결에 별도 CANoe 인스턴스를 사용하게 합니다.\n\n"
            "1. CANoe 작업을 저장하고 모든 CANoe 창을 직접 닫으세요.\n"
            "2. ‘상태 다시 확인’ → ‘cfg별 CANoe 연결 켜기’를 누르세요. 닫으면 저장된 CAN·Diag 연결을 다시 확인합니다.\n\n"
            "이 설정은 로그 블록 선택이나 .cfg 내용을 바꾸지 않습니다. Vector 연결 모드를 해당 설치본 전체에 적용합니다. "
            "다른 COM 도구 및 ActiveX/.NET 패널에서 추가 CANoe 창이 열릴 수 있습니다. 문제가 생기면 CANoe 창을 모두 닫고 "
            "기본 공유 연결로 복구하세요. 원본 can.ini를 같은 폴더에 백업합니다.",
            "AutoLog connects one selected .cfg per target and controls one logging block in that configuration.\n"
            "Example: CAN .cfg → CAN logging block / Diag .cfg → Diag logging block\n\n"
            "This setting is needed only when using both the CAN and Diag .cfg files. Each must open in a separate CANoe instance. "
            "Default COM activation may return "
            "the first CANoe window to the second request, causing Diag to attach to the CAN configuration. This setting "
            "makes AutoLog use a separate CANoe instance for each .cfg connection.\n\n"
            "1. Save your CANoe work and close all CANoe windows yourself.\n"
            "2. Refresh status, then enable one CANoe instance per cfg. On close, AutoLog rechecks saved CAN and Diag connections.\n\n"
            "This does not change logging block choices or .cfg contents. It changes the Vector connection mode for this "
            "entire CANoe installation. Other COM tools and ActiveX/.NET panels may open extra CANoe windows. To undo it, "
            "close all CANoe windows and restore the default shared mode. The original can.ini is backed up beside it."))
        guide.setWordWrap(True)
        layout.addWidget(guide)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)
        self.enable_button = QPushButton(self._t("cfg별 CANoe 연결 켜기", "Enable one CANoe instance per cfg"))
        self.enable_button.setProperty("variant", "primary")
        self.enable_button.clicked.connect(lambda: self._apply(True))
        layout.addWidget(self.enable_button)
        self.restore_button = QPushButton(self._t("기본 공유 연결로 복구", "Restore shared default mode"))
        self.restore_button.clicked.connect(lambda: self._apply(False))
        layout.addWidget(self.restore_button)
        self.refresh_button = QPushButton(self._t("상태 다시 확인", "Refresh status"))
        self.refresh_button.clicked.connect(self._load)
        layout.addWidget(self.refresh_button)
        close = QPushButton(self._t("닫기", "Close"))
        close.clicked.connect(self.close)
        layout.addWidget(close)
        self._load()

    def _t(self, ko, en):
        return en if self.language == "en" else ko

    def _load(self):
        try:
            self.path = registered_settings_file()
            self.expected = self.path.read_bytes()
            enabled = single_client_enabled(self.path)
            processes = canoe_process_ids()
            self.status.setText(self._t("연결 방식: cfg별 독립 연결" if enabled else "연결 방식: 기본 (COM 요청이 열린 창을 재사용할 수 있음)",
                                        "Connection mode: one instance per cfg" if enabled else "Connection mode: default (COM requests may reuse an open window)")
                                + "\n" + str(self.path))
            if processes:
                self.status.setText(self.status.text() + "\n" + self._t(
                    f"CANoe 인스턴스 {len(processes)}개가 실행 중입니다. 작업을 저장하고 모두 닫은 뒤 ‘상태 다시 확인’을 누르세요.",
                    f"{len(processes)} CANoe instance(s) are running. Save your work, close them, then refresh status."))
            self.enable_button.setEnabled(not enabled and not processes)
            self.restore_button.setEnabled(enabled and not processes)
        except Exception as error:
            self.status.setText(str(error))
            self.enable_button.setEnabled(False)
            self.restore_button.setEnabled(False)
            log.exception("canoe.com_setup_unavailable")

    def _apply(self, enabled):
        try:
            result = set_single_client(self.path, enabled, expected=self.expected)
            self.applied_enabled = result["enabled"]
            self._load()
            self.status.setText(self.status.text() + "\n" + self._t("적용 완료. 백업: ", "Applied. Backup: ") +
                                result.get("backup", ""))
        except Exception as error:
            log.exception("canoe.com_setup_failed")
            self.status.setText(self._t("설정을 바꾸지 못했습니다: ", "Could not apply the setting: ") + str(error))
