"""Review and explicitly apply Vector's independent-client setting."""

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from vil_logging.diagnostics.canoe_setup import (
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
        self.setWindowTitle(self._t("CANoe 독립 연결 설정", "CANoe independent connection setup"))
        self.resize(570, 400)
        apply_theme(self)
        layout = QVBoxLayout(self)
        guide = QLabel(self._t(
            "CAN과 Diag를 별도 CANoe 창으로 연결하려면 다중 COM 연결 설정이 필요합니다.\n\n"
            "1. CANoe에서 작업을 보관한 뒤 모든 CANoe 창을 직접 닫으세요.\n"
            "2. 아래 적용 버튼을 누른 뒤 AutoLog에서 연결 확인을 다시 누르세요.\n\n"
            "이 설정은 해당 CANoe 설치본 전체에 적용됩니다. Vector는 다른 COM 도구 및 ActiveX/.NET 패널에서 "
            "추가 창이 열릴 수 있다고 안내합니다. 문제가 생기면 모든 CANoe 창을 닫고 기본 연결로 복구하세요. "
            "원본 can.ini는 같은 폴더에 백업하며 .cfg는 수정하지 않습니다.",
            "Independent CAN and Diag windows require Vector's single-client COM mode.\n\n"
            "1. Save your work in CANoe and close all CANoe windows yourself.\n"
            "2. Apply below, then check the connections in AutoLog again.\n\n"
            "This affects the whole CANoe installation. Vector notes that other COM tools and ActiveX/.NET panels "
            "may open additional windows. If needed, close all CANoe windows and restore default activation. "
            "The original can.ini is backed up beside it; .cfg files are untouched."))
        guide.setWordWrap(True)
        layout.addWidget(guide)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)
        self.enable_button = QPushButton(self._t("다중 연결 적용", "Enable independent connections"))
        self.enable_button.setProperty("variant", "primary")
        self.enable_button.clicked.connect(lambda: self._apply(True))
        layout.addWidget(self.enable_button)
        self.restore_button = QPushButton(self._t("기본 연결로 복구", "Restore default activation"))
        self.restore_button.clicked.connect(lambda: self._apply(False))
        layout.addWidget(self.restore_button)
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
            self.status.setText(self._t("현재: 다중 연결 켜짐" if enabled else "현재: 기본 연결 모드",
                                        "Current: independent clients enabled" if enabled else "Current: default activation")
                                + "\n" + str(self.path))
            self.enable_button.setEnabled(not enabled)
            self.restore_button.setEnabled(enabled)
        except Exception as error:
            self.status.setText(str(error))
            self.enable_button.setEnabled(False)
            self.restore_button.setEnabled(False)
            log.exception("canoe.com_setup_unavailable")

    def _apply(self, enabled):
        try:
            result = set_single_client(self.path, enabled, expected=self.expected)
            self._load()
            self.status.setText(self.status.text() + "\n" + self._t("적용 완료. 백업: ", "Applied. Backup: ") +
                                result.get("backup", ""))
        except Exception as error:
            log.exception("canoe.com_setup_failed")
            self.status.setText(self._t("설정을 바꾸지 못했습니다: ", "Could not apply the setting: ") + str(error))
