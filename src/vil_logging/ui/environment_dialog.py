"""Readable readiness summary; raw diagnostics stay behind a details toggle."""

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from vil_logging.contracts.models import Role

from .theme import apply_theme, refresh_style


class EnvironmentDialog(QDialog):
    refresh_requested = Signal()
    settings_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._language = "ko"
        self._environment = {}
        self._connections = {}
        self._busy = False
        self._error = ""
        self._roles = tuple(Role)
        self._install_actions = {}
        self.setObjectName("environmentDialog")
        self.resize(660, 740)
        self.setMinimumSize(580, 520)
        apply_theme(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 22, 24, 20)
        outer.setSpacing(12)
        heading = QHBoxLayout()
        self.title = QLabel()
        self.title.setProperty("variant", "title")
        heading.addWidget(self.title, 1)
        self.summary = QLabel()
        self.summary.setProperty("variant", "status")
        heading.addWidget(self.summary)
        outer.addLayout(heading)
        self.intro = QLabel()
        self.intro.setWordWrap(True)
        self.intro.setProperty("variant", "muted")
        outer.addWidget(self.intro)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setProperty("tone", "error")
        self.error_label.hide()
        outer.addWidget(self.error_label)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        cards_layout = QVBoxLayout(body)
        cards_layout.setContentsMargins(0, 0, 3, 0)
        cards_layout.setSpacing(10)
        self._cards_layout = cards_layout
        self.cards = {}
        for key, section in (("canoe", "canoe"), ("tshark", "ethernet"), ("helpers", "ethernet"),
                             ("network", "ethernet"), ("npcap", "ethernet")):
            card = QFrame()
            card.setProperty("panel", True)
            layout = QVBoxLayout(card)
            layout.setContentsMargins(16, 13, 16, 13)
            top = QHBoxLayout()
            name = QLabel()
            name.setProperty("variant", "section")
            top.addWidget(name, 1)
            status = QLabel()
            status.setProperty("variant", "status")
            top.addWidget(status)
            layout.addLayout(top)
            message = QLabel()
            message.setObjectName(key + "ReadinessMessage")
            message.setWordWrap(True)
            message.setTextFormat(Qt.TextFormat.PlainText)
            message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(message)
            action = QPushButton()
            action.setProperty("variant", "ghost")
            action.clicked.connect(lambda _checked=False, value=key, target=section: self._act(value, target))
            layout.addWidget(action, 0, Qt.AlignmentFlag.AlignLeft)
            self.cards[key] = (name, status, message, action)
            cards_layout.addWidget(card)
        cards_layout.addStretch()
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        self.details_button = QToolButton()
        self.details_button.setCheckable(True)
        self.details_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.details_button.setArrowType(Qt.ArrowType.RightArrow)
        self.details_button.toggled.connect(self._toggle_details)
        outer.addWidget(self.details_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.details = QPlainTextEdit()
        self.details.setObjectName("technicalDetails")
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(170)
        self.details.hide()
        outer.addWidget(self.details)
        self.scope = QLabel()
        self.scope.setWordWrap(True)
        self.scope.setProperty("variant", "helper")
        outer.addWidget(self.scope)
        actions = QHBoxLayout()
        self.refresh_button = QPushButton()
        self.refresh_button.clicked.connect(self.refresh_requested)
        actions.addWidget(self.refresh_button)
        actions.addStretch()
        self.close_button = QPushButton()
        self.close_button.setProperty("variant", "primary")
        self.close_button.clicked.connect(self.hide)
        actions.addWidget(self.close_button)
        outer.addLayout(actions)
        self.set_language("ko")

    def _t(self, ko: str, en: str) -> str:
        from .i18n import localized
        return localized(ko, en, self._language)

    def set_roles(self, roles):
        self._roles = tuple(roles)
        order = ["tshark", "npcap", "helpers", "network", "canoe"]
        if Role.ETHERNET not in self._roles:
            order = ["canoe", "tshark", "npcap", "helpers", "network"]
        for index, key in enumerate(order):
            self._cards_layout.insertWidget(index, self.cards[key][0].parentWidget())
        self._render()

    def _act(self, key, section):
        self.settings_requested.emit(section)

    def _toggle_details(self, checked: bool):
        self.details.setVisible(checked)
        self.details_button.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)

    def set_busy(self, busy: bool):
        self._busy = busy
        if busy:
            self._error = ""
            self.error_label.hide()
        self.refresh_button.setEnabled(not busy)
        self._render()

    def set_error(self, message: str):
        self._error = message
        self._busy = False
        self.error_label.setText(message)
        self.error_label.setVisible(bool(message))
        self.refresh_button.setEnabled(True)
        self._render()

    def set_report(self, environment_report: dict, connections_report: dict | None = None):
        self._environment = environment_report or {}
        if connections_report is not None:
            self._connections = connections_report
        self._render()

    def set_language(self, language: str):
        self._language = language if language in {"ko", "en", "zh"} else "ko"
        self.setWindowTitle(self._t("환경 확인", "Readiness check"))
        self.title.setText(self.windowTitle())
        self.intro.setText(self._t("설치된 도구와 네트워크를 확인하고, 필요한 설정을 안내합니다.",
                                  "Check installed tools and networks, with a clear next step for each item."))
        self.details_button.setText(self._t("기술 상세 보기", "Technical details"))
        self.scope.setText(self._t("이 확인은 패킷 기록을 시작하지 않습니다. 실제 장비 취득은 별도로 확인합니다.",
                                  "This check does not start recording. Live acquisition is verified separately."))
        self.refresh_button.setText(self._t("설치·설정 후 다시 확인", "Check after setup"))
        self.close_button.setText(self._t("닫기", "Close"))
        self._render()

    def _render(self):
        data, connections = self._environment, self._connections
        canoe = data.get("canoe", {})
        installations = canoe.get("executables", [])
        canoe_ok = bool(installations)
        canoe_message = self._t("CANoe 설치를 찾지 못했습니다. 시험 PC에 CANoe가 설치되어 있는지 확인하세요.",
                                "CANoe was not found. Check its installation on the test PC.")
        if canoe_ok:
            version = installations[0].get("version_check", {}).get("file_version", "")
            canoe_message = self._t("CANoe {version} 설치를 찾았습니다. 사용할 .cfg 파일을 선택하세요.",
                                    "CANoe {version} was found. Choose the configuration to use.").format(version=version)
        tool = connections.get("tshark", {})
        if not tool and data.get("tshark", {}).get("path"):
            observed = data["tshark"]
            tool = {"status": "ready" if observed.get("version_check", {}).get("status") == "present" else "invalid",
                    "path": observed["path"]}
        tool_ok = tool.get("status") == "ready"
        tool_message = tool.get("message_" + self._language) or self._t(
            "Wireshark의 TShark가 필요합니다. 설정에서 실행 파일을 직접 선택하세요.",
            "TShark, included with Wireshark, is needed. Select its executable in Settings.")
        if tool_ok:
            tool_message = (tool.get("version") or self._t("캡처 도구를 찾았습니다.", "Capture tool found."))
            tool_message += "\n" + tool.get("path", "")
        selected = next((item for item in connections.get("interfaces", [])
                         if item.get("id") == connections.get("selected_nic_id")), None)
        network_ok = bool(selected)
        network_message = self._t("Ethernet 설정에서 장비에 연결된 네트워크 이름을 선택하세요.",
                                  "Choose the network connected to your device in Ethernet settings.")
        if connections.get("remembered_nic_missing"):
            network_message = self._t("지난번 네트워크가 현재 보이지 않습니다. 연결을 확인하거나 다시 선택하세요.",
                                      "The previous network is missing. Check the connection or choose again.")
        elif selected:
            network_message = selected.get("name", "")
            if selected.get("description") and selected["description"] != network_message:
                network_message += "\n" + selected["description"]
        driver = connections.get("npcap") or data.get("npcap", {})
        driver_ok = driver.get("status") == "present"
        driver_message = driver.get("message_" + self._language) or self._t(
            "실시간 Ethernet 취득에는 Npcap이 필요합니다. 별도 설치 안내를 확인하세요.",
            "Live Ethernet capture needs Npcap. Refer to your installation guide.")
        helpers_ok = all(data.get(name, {}).get("version_check", {}).get("status") == "present"
                         for name in ("dumpcap", "capinfos"))
        helpers_message = self._t("dumpcap·capinfos를 확인했습니다.", "dumpcap and capinfos were found.") if helpers_ok else self._t(
            "캡처·파일 검사에 dumpcap과 capinfos가 필요합니다. 별도 설치 안내를 확인하세요.",
            "Capture and file inspection require dumpcap and capinfos. Refer to your installation guide.")
        rows = {
            "canoe": ("CANoe", canoe_ok, canoe_message, self._t("구성 파일 설정", "Choose configuration")),
            "tshark": (self._t("캡처 도구", "Capture tool"), tool_ok, tool_message,
                       self._t("캡처 도구 설정", "Capture tool settings")),
            "helpers": (self._t("캡처·파일 검사 도구", "Capture and file inspection"), helpers_ok,
                        helpers_message, self._t("Ethernet 설정", "Ethernet settings")),
            "network": (self._t("Ethernet 네트워크", "Ethernet network"), network_ok, network_message,
                        self._t("네트워크 선택", "Choose network")),
            "npcap": (self._t("캡처 드라이버 · Npcap", "Capture driver · Npcap"), driver_ok,
                      driver_message, self._t("드라이버 확인 방법", "Driver guidance")),
        }
        for key, (title, ready, message, action) in rows.items():
            name_label, status_label, message_label, action_button = self.cards[key]
            applicable = ((Role.CAN in self._roles or Role.DIAG in self._roles) if key == "canoe"
                          else Role.ETHERNET in self._roles)
            name_label.setText(title)
            status_label.setText(self._t("선택 대상 아님", "Not selected") if not applicable else
                                 self._t("확인됨", "Found") if ready else self._t("확인 필요", "Needs attention"))
            status_label.setProperty("tone", "neutral" if not applicable else "ready" if ready else "attention")
            refresh_style(status_label)
            message_label.setText(message)
            action_button.setText(action)
            action_button.setVisible(key != "npcap")
        attention = sum(not row[1] for key, row in rows.items() if
                        ((Role.CAN in self._roles or Role.DIAG in self._roles) if key == "canoe"
                         else Role.ETHERNET in self._roles))
        self.summary.setText(self._t("확인 중…", "Checking…") if self._busy else
                             self._t("{count}곳 확인 필요", "{count} need attention").format(count=attention) if attention else
                             self._t("설정 확인 완료", "Checks complete"))
        self.summary.setProperty("tone", "checking" if self._busy else "attention" if attention else "ready")
        if self._error:
            self.summary.setText(self._t("확인에 실패했습니다", "Check failed"))
            self.summary.setProperty("tone", "error")
        refresh_style(self.summary)
        self.details.setPlainText(json.dumps({"environment": data, "connections": connections},
                                            ensure_ascii=False, indent=2))
