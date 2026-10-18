"""Interactive vendor installation guidance for online and offline PCs."""

import logging
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QFileDialog, QLabel, QPushButton, QVBoxLayout

from vil_logging.diagnostics.readiness import INSTALL_URLS

from .theme import apply_theme

log = logging.getLogger(__name__)
GUIDES = {
    "wireshark": ("Wireshark", (
        "1. 공식 페이지에서 Windows x64 설치파일을 받으세요.\n"
        "2. TShark 구성요소와 Npcap 설치를 선택하세요.\n"
        "3. 설치가 끝나면 아래 ‘설치 후 다시 확인’을 누르세요.",
        "1. Download the Windows x64 installer from the official page.\n"
        "2. Include TShark and install Npcap.\n"
        "3. When installation finishes, choose Check after installation below.")),
    "npcap": ("Npcap", (
        "1. 공식 페이지 또는 회사에서 제공한 Npcap 설치파일을 실행하세요.\n"
        "2. Windows 관리자 권한 요청과 설치창을 완료하세요.\n"
        "3. 재부팅 요청이 있으면 재부팅 후 AutoLog를 다시 실행하세요.",
        "1. Use the official Npcap installer or your company-provided installer.\n"
        "2. Complete the Windows administrator prompt and installer.\n"
        "3. If a restart is requested, restart Windows and reopen AutoLog.")),
    "canoe": ("CANoe", (
        "1. 회사에서 사용하는 CANoe 설치본과 라이선스를 준비하세요.\n"
        "2. CANoe와 사용하는 Vector 장비 드라이버를 설치하세요.\n"
        "3. CANoe에서 라이선스를 확인한 뒤 AutoLog에서 .cfg를 선택하세요.\n"
        "4. CAN+Diag는 설정 → CAN·Diag 구성 → CANoe 독립 연결 설정을 적용하세요.\n"
        "CAN/Diag 구간 기록은 시험 PC의 구성과 장비로 검증해야 합니다.",
        "1. Obtain your company-approved CANoe installer and license.\n"
        "2. Install CANoe and the drivers for your Vector hardware.\n"
        "3. Verify the license in CANoe, then select the .cfg in AutoLog.\n"
        "4. For CAN+Diag, use Settings → CAN·Diag → CANoe independent connection setup.\n"
        "Verify CAN/Diag segment recording with your test PC configuration and hardware.")),
}


class InstallationDialog(QDialog):
    refresh_requested = Signal()

    def __init__(self, tool: str, language: str = "ko", parent=None):
        super().__init__(parent)
        self.tool = tool
        self.language = language
        title, guides = GUIDES[tool]
        self.setWindowTitle(f"{title} · " + self._t("설치 안내", "Installation"))
        self.resize(540, 370)
        apply_theme(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)
        heading = QLabel(self.windowTitle())
        heading.setProperty("variant", "section")
        layout.addWidget(heading)
        guide = QLabel(guides[language == "en"])
        guide.setWordWrap(True)
        layout.addWidget(guide)
        self.online_button = QPushButton(self._t("공식 설치 페이지 열기", "Open official installation page"))
        self.online_button.clicked.connect(self._open_online)
        layout.addWidget(self.online_button)
        self.local_button = QPushButton(self._t("내 PC의 설치파일 실행…", "Run an installer on this PC…"))
        self.local_button.clicked.connect(self._open_local)
        layout.addWidget(self.local_button)
        self.feedback = QLabel(self._t(
            "인터넷이 없는 PC에서는 USB 등으로 가져온 회사 승인 설치파일을 선택하세요.",
            "On an offline PC, select a company-approved installer brought on USB or other media."))
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        self.refresh_button = QPushButton(self._t("설치 후 다시 확인", "Check after installation"))
        self.refresh_button.setProperty("variant", "primary")
        self.refresh_button.clicked.connect(self._refresh)
        layout.addWidget(self.refresh_button)

    def _t(self, ko, en):
        return en if self.language == "en" else ko

    def _open_online(self):
        opened = QDesktopServices.openUrl(QUrl(INSTALL_URLS[self.tool]))
        log.info("installation.page_opened", extra={"tool": self.tool, "opened": opened})
        self.feedback.setText(self._t("브라우저에서 다운로드와 설치를 완료한 뒤 다시 확인하세요.",
                                      "Complete the download and installation, then check again.") if opened else
                              self._t("브라우저를 열지 못했습니다: ", "Could not open the browser: ") +
                              INSTALL_URLS[self.tool])

    def _open_local(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, self._t("설치파일 선택", "Choose installer"), "", "Windows installer (*.exe *.msi)")
        if not filename:
            return
        path = Path(filename)
        if not path.is_file() or path.suffix.lower() not in {".exe", ".msi"}:
            self.feedback.setText(self._t("실행할 설치파일을 찾지 못했습니다.", "Installer file not found."))
            return
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))
        log.info("installation.local_opened", extra={"tool": self.tool, "path": str(path), "opened": opened})
        self.feedback.setText(self._t("설치창을 완료한 뒤 ‘설치 후 다시 확인’을 누르세요.",
                                      "Complete the installer, then check again.") if opened else
                              self._t("설치파일을 열지 못했습니다. 권한과 파일을 확인하세요.",
                                      "Could not open the installer. Check the file and permissions."))

    def _refresh(self):
        self.hide()
        self.refresh_requested.emit()
