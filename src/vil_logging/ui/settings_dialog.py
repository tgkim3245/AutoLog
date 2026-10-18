"""Remembered connection choices and visible connection preparation feedback."""

import logging
from collections import deque
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from vil_logging import __version__
from vil_logging.contracts.models import AppSettings, Role, TargetSnapshot
from vil_logging.storage.naming import NamingError, parse_index

from .i18n import tr
from .theme import ThemedComboBox, apply_theme, refresh_style

logger = logging.getLogger(__name__)
PREFERENCES = ("output_dir", "can_cfg", "diag_cfg", "tshark_path", "nic_id", "ethernet_format", "ethernet_buffer_mib",
               "can_logging_block", "diag_logging_block")
TEXT = {
    "intro": ("파일과 네트워크 선택은 자동으로 기억합니다.", "File and network choices are saved automatically."),
    "storage": ("저장 설정", "Storage"), "canoe": ("CAN · Diag 구성", "CAN · Diag configuration"),
    "ethernet": ("Ethernet 연결", "Ethernet connection"),
    "network": ("캡처할 네트워크", "Network to capture"),
    "choose_network": ("네트워크를 선택하세요", "Choose a network"),
    "missing_network": ("이전 선택 · 현재 찾을 수 없음", "Previous choice · currently unavailable"),
    "up": ("연결됨", "Connected"), "down": ("연결 끊김", "Disconnected"),
    "unknown": ("상태 미확인", "Status unknown"),
    "capture_attention": ("캡처 확인 필요", "Capture access needs checking"),
    "tool": ("Wireshark 캡처 도구", "Wireshark capture tool"),
    "tool_help": ("TShark는 Wireshark에 포함된 캡처 도구입니다. 설치 위치를 자동으로 찾습니다.",
                  "TShark is the capture tool included with Wireshark. Its location is detected automatically."),
    "find": ("다시 찾기", "Find again"), "select": ("직접 선택", "Choose file"),
    "finding": ("캡처 도구와 네트워크를 찾고 있습니다…", "Finding the capture tool and networks…"),
    "tool_pending": ("설정창을 열면 설치된 캡처 도구를 찾습니다.", "The capture tool is detected when you open settings."),
    "tool_found": ("캡처 도구를 찾았습니다", "Capture tool found"),
    "tool_missing": ("Wireshark 캡처 도구를 찾지 못했습니다.", "Wireshark capture tool was not found."),
    "tool_next": ("Wireshark를 설치한 뒤 다시 찾거나 tshark.exe를 직접 선택하세요.",
                  "Install Wireshark and find again, or choose tshark.exe."),
    "network_help": ("장비가 연결된 네트워크 이름을 선택하세요. 선택한 장치는 다음 실행에도 기억합니다.",
                     "Choose the network connected to your device. Your choice is remembered for the next launch."),
    "can_help": (".cfg를 선택하고 연결 확인을 누르면 전용 CANoe 창을 엽니다. 그 창에서 측정을 시작하세요. 구간 기록은 AutoLog로 제어합니다.",
                 "Choose .cfg and check connection to open a dedicated CANoe window. Start measurement there; control segment recording from AutoLog."),
    "naming_help": ("파일명과 다음 번호를 바꾼 뒤 적용하세요. 번호 앞의 _는 자동으로 넣습니다. 경로 선택은 바로 저장됩니다.",
                    "Apply changes to the filename prefix and next number. An underscore is added before the index. Path choices save immediately."),
    "saved": ("선택을 저장했습니다.", "Choices saved."),
    "saving": ("선택을 저장하고 있습니다…", "Saving your choices…"),
    "check": ("연결 확인", "Check connection"), "checking": ("확인 중…", "Checking…"),
    "ready": ("준비됨", "Ready"), "attention": ("확인 필요", "Needs attention"),
    "error": ("연결 오류", "Connection error"),
    "unprepared": ("아직 연결을 확인하지 않았습니다.", "The connection has not been checked yet."),
    "wait": ("잠시만 기다려주세요.", "Please wait a moment."),
    "cfg_next": ("구성 파일을 확인하거나 다시 선택한 뒤 연결 확인을 눌러주세요.",
                 "Check or choose the configuration file, then check the connection again."),
    "network_next": ("캡처 도구와 장비가 연결된 네트워크를 확인한 뒤 다시 눌러주세요.",
                     "Check the capture tool and the network connected to your device, then try again."),
    "ready_next": ("메인 화면에서 대상을 선택한 뒤 logging을 시작하세요.",
                   "Select the target on the main screen, then start logging."),
    "scope": ("환경·연결 확인은 실제 캡처 성공을 의미하지 않습니다.",
              "Environment and connection checks do not establish successful capture."),
    "timeout": ("검색 응답이 지연되고 있습니다. 다시 찾기를 눌러 재시도하세요.",
                "Discovery is taking too long. Choose Find again to retry."),
    "npcap": ("Npcap 설치 페이지", "Npcap installation page"),
    "format_help": ("기본 저장 형식은 pcap입니다. 다른 형식을 선택하면 다음 실행에도 기억합니다.",
                    "The default is pcap. A different choice is remembered for the next launch."),
    "npcap_help": ("실제 캡처에 필요한 Npcap이 없습니다. 설치 후 다시 찾기를 누르세요.",
                   "Npcap is required for live capture. Install it, then choose Find again."),
}


class SettingsDialog(QDialog):
    installation_requested = Signal(str)
    settings_applied = Signal(object)
    preferences_changed = Signal(object)
    prepare_requested = Signal(object)
    environment_requested = Signal()
    discovery_requested = Signal(bool)
    npcap_requested = Signal()
    exit_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = AppSettings()
        self._language = "ko"
        self._busy = self._updating = self._discovering = self._discovery_started = False
        self._dirty: set[str] = set()
        self._revision = self._discovery_revision = 0
        self._field_revision: dict[str, int] = {}
        self._pending_patches: deque[tuple[int, dict]] = deque()
        self._discovery: dict = {}
        self._discovery_error = ""
        self._discovery_timer = QTimer(self)
        self._discovery_timer.setSingleShot(True)
        self._discovery_timer.setInterval(30_000)
        self._discovery_timer.timeout.connect(self._discovery_timed_out)
        self._reports: dict[Role, dict] = {}
        self._preparing: set[Role] = set()
        self.targets = {role: TargetSnapshot(role) for role in Role}
        self.fields: dict[str, QLineEdit] = {}
        self.block_inputs = {}
        self.block_labels = {}
        self.labels: dict[str, QLabel] = {}
        self.browse_buttons: list[QPushButton] = []
        self.prepare_buttons: dict[Role, QPushButton] = {}
        self.target_labels: dict[Role, QLabel] = {}
        self.result_details: dict[Role, QLabel] = {}
        self.next_actions: dict[Role, QLabel] = {}
        self._preparation_cards: dict[Role, QFrame] = {}
        self.setObjectName("settingsDialog")
        self.setMinimumSize(640, 590)
        self.resize(700, 730)
        apply_theme(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 22, 24, 20)
        outer.setSpacing(14)
        heading_row = QHBoxLayout()
        self.heading = QLabel()
        self.heading.setProperty("variant", "title")
        heading_row.addWidget(self.heading, 1)
        self.version_label = QLabel(f"v{__version__}")
        self.version_label.setProperty("variant", "muted")
        heading_row.addWidget(self.version_label)
        outer.addLayout(heading_row)
        self.hint = self._helper()
        outer.addWidget(self.hint)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        storage, layout = self._page()
        self.naming_hint = self._helper()
        layout.addWidget(self.naming_hint)
        form = QFormLayout()
        form.setSpacing(12)
        for key, title, picker in (("output_dir", "output", "folder"),
                                   ("prefix", "prefix", None), ("next_index", "next_index", None)):
            self._field(form, key, title, picker)
        layout.addLayout(form)
        self.fields["next_index"].setToolTip("0 이상의 정수 / Non-negative integer")
        self.apply_button = QPushButton()
        self.apply_button.setObjectName("applySettingsButton")
        self.apply_button.setProperty("variant", "primary")
        self.apply_button.clicked.connect(self._apply)
        layout.addWidget(self.apply_button, 0, Qt.AlignmentFlag.AlignRight)
        layout.addStretch()
        self.tabs.addTab(storage, "")
        canoe, layout = self._page()
        self.can_hint = self._helper()
        layout.addWidget(self.can_hint)
        self.canoe_setup_button = QPushButton()
        self.canoe_setup_button.setObjectName("canoeSetupButton")
        self.canoe_setup_button.clicked.connect(self._open_canoe_setup)
        layout.addWidget(self.canoe_setup_button, 0, Qt.AlignmentFlag.AlignLeft)
        for role, key in ((Role.CAN, "can_cfg"), (Role.DIAG, "diag_cfg")):
            form = QFormLayout()
            self._field(form, key, role.label + " .cfg", "cfg")
            block_key = ("can" if role == Role.CAN else "diag") + "_logging_block"
            combo = ThemedComboBox()
            combo.setObjectName(block_key + "ComboBox")
            self.block_inputs[block_key] = combo
            combo.addItem("", "")
            combo.currentIndexChanged.connect(lambda _index, k=block_key: self._block_changed(k))
            self.block_labels[block_key] = QLabel()
            form.addRow(self.block_labels[block_key], combo)
            self.fields[key].textChanged.connect(lambda _value, k=block_key: self._reset_blocks(k))
            layout.addLayout(form)
            layout.addWidget(self._preparation_box(role))
        layout.addStretch()
        self.tabs.addTab(canoe, "")
        ethernet, layout = self._page()
        self.tool_heading = QLabel()
        self.tool_heading.setProperty("variant", "section")
        layout.addWidget(self.tool_heading)
        self.tool_hint = self._helper()
        layout.addWidget(self.tool_hint)
        form = QFormLayout()
        self._field(form, "tshark_path", "tshark", "tool")
        layout.addLayout(form)
        self.tool_status = self._helper()
        self.tool_status.setObjectName("captureToolStatus")
        layout.addWidget(self.tool_status)
        self.find_button = QPushButton()
        self.find_button.setObjectName("discoverConnectionsButton")
        self.find_button.clicked.connect(lambda: self._request_discovery(reset_tool=True))
        layout.addWidget(self.find_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.install_button = QPushButton()
        self.install_button.clicked.connect(lambda: self.installation_requested.emit("wireshark"))
        layout.addWidget(self.install_button, 0, Qt.AlignmentFlag.AlignLeft)
        form = QFormLayout()
        self.network_label = QLabel()
        self.nic_input = ThemedComboBox()
        self.nic_input.setObjectName("nicAdapterComboBox")
        self.nic_input.setMinimumContentsLength(28)
        self.nic_input.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.nic_input.currentIndexChanged.connect(self._nic_changed)
        form.addRow(self.network_label, self.nic_input)
        self.format_label = QLabel()
        self.format_input = ThemedComboBox()
        self.format_input.setObjectName("ethernetFormatComboBox")
        self.format_input.addItems(["pcap", "pcapng"])
        self.format_input.currentTextChanged.connect(self._format_changed)
        form.addRow(self.format_label, self.format_input)
        self.buffer_label = QLabel()
        self.buffer_input = ThemedComboBox()
        self.buffer_input.setObjectName("ethernetBufferComboBox")
        for value in (16, 32, 64, 128, 256):
            self.buffer_input.addItem(f"{value} MiB", str(value))
        self.buffer_input.currentIndexChanged.connect(self._buffer_changed)
        form.addRow(self.buffer_label, self.buffer_input)
        layout.addLayout(form)
        self.buffer_hint = self._helper()
        layout.addWidget(self.buffer_hint)
        self.network_hint = self._helper()
        layout.addWidget(self.network_hint)
        self.driver_status = self._helper()
        layout.addWidget(self.driver_status)
        self.npcap_button = QPushButton()
        self.npcap_button.setProperty("variant", "secondary")
        self.npcap_button.clicked.connect(self.npcap_requested)
        self.npcap_button.hide()
        layout.addWidget(self.npcap_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._preparation_box(Role.ETHERNET))
        layout.addStretch()
        self.tabs.addTab(ethernet, "")
        self.feedback = self._helper()
        self.feedback.setObjectName("settingsFeedback")
        outer.addWidget(self.feedback)
        self.scope_hint = self._helper()
        outer.addWidget(self.scope_hint)
        actions = QHBoxLayout()
        self.environment_button = QPushButton()
        self.environment_button.clicked.connect(self.environment_requested)
        self.exit_button = QPushButton()
        self.exit_button.setProperty("variant", "ghost")
        self.exit_button.clicked.connect(self.exit_requested)
        self.close_button = QPushButton()
        self.close_button.clicked.connect(self.hide)
        actions.addWidget(self.environment_button)
        actions.addStretch()
        actions.addWidget(self.exit_button)
        actions.addWidget(self.close_button)
        outer.addLayout(actions)
        self.set_settings(self._settings)

    def _t(self, key: str) -> str:
        return TEXT[key][self._language == "en"]

    @staticmethod
    def _helper() -> QLabel:
        label = QLabel()
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setProperty("variant", "helper")
        return label

    def _open_canoe_setup(self):
        from .canoe_setup_dialog import CanoeSetupDialog
        dialog = CanoeSetupDialog(self._language, self)
        dialog.exec()

    @staticmethod
    def _page():
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 18, 16, 16)
        layout.setSpacing(12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        return scroll, layout

    def _field(self, form, key, title, picker):
        field = QLineEdit()
        field.setObjectName(key + "Input")
        field.textChanged.connect(lambda _text, k=key: self._mark_dirty(k))
        if key in PREFERENCES:
            field.editingFinished.connect(lambda k=key: self._save_preferences((k,)))
        self.fields[key] = field
        label = QLabel()
        label.setProperty("translationKey", title)
        self.labels[key] = label
        if not picker:
            form.addRow(label, field)
            return
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(field, 1)
        button = QPushButton()
        button.setProperty("picker", picker)
        button.clicked.connect(lambda _checked=False, k=key, p=picker: self._browse(k, p))
        self.browse_buttons.append(button)
        row.addWidget(button)
        holder = QWidget()
        holder.setLayout(row)
        form.addRow(label, holder)

    def _preparation_box(self, role):
        frame = QFrame()
        frame.setProperty("panel", True)
        frame.setProperty("role", "card")
        frame.setObjectName(f"preparation{role.value}Card")
        self._preparation_cards[role] = frame
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        row = QHBoxLayout()
        title = QLabel(role.label)
        title.setProperty("variant", "section")
        row.addWidget(title)
        row.addStretch()
        button = QPushButton()
        button.setObjectName(f"prepare{role.label}Button")
        button.setProperty("variant", "secondary")
        button.clicked.connect(lambda _checked=False, r=role: self._prepare(r))
        self.prepare_buttons[role] = button
        row.addWidget(button)
        layout.addLayout(row)
        status = self._helper()
        status.setObjectName(f"preparation{role.value}Status")
        status.setProperty("variant", "status")
        self.target_labels[role] = status
        layout.addWidget(status)
        self.result_details[role] = self._helper()
        layout.addWidget(self.result_details[role])
        self.next_actions[role] = self._helper()
        self.next_actions[role].setObjectName(f"preparation{role.value}NextAction")
        layout.addWidget(self.next_actions[role])
        return frame

    def showEvent(self, event):
        super().showEvent(event)
        if not self._discovery_started:
            self._request_discovery()

    def _mark_dirty(self, key):
        if not self._updating:
            self._revision += 1
            self._field_revision[key] = self._revision
            self._dirty.add(key)

    def _current(self, key):
        if key in self.block_inputs:
            return self.block_inputs[key].currentData() or ""
        if key == "nic_id":
            return self.nic_input.currentData() or ""
        if key == "ethernet_format":
            return self.format_input.currentText()
        if key == "ethernet_buffer_mib":
            return self.buffer_input.currentData()
        return self.fields[key].text().strip()

    def _block_changed(self, key):
        self._mark_dirty(key)
        self._save_preferences((key,))

    def _reset_blocks(self, key):
        if self._updating:
            return
        with QSignalBlocker(self.block_inputs[key]):
            self.block_inputs[key].clear()
            self.block_inputs[key].addItem("연결 후 블록 선택" if self._language == "ko" else "Choose block after connection", "")
        self._mark_dirty(key)

    def _save_preferences(self, keys, *, force=False):
        if self._busy or self._updating:
            return
        patch = {key: self._current(key) for key in keys if force or key in self._dirty}
        if patch:
            # A later edit supersedes only the same fields in an older request.
            # ACKs for the older value must not keep the saving indicator stuck.
            pending = deque()
            for version, previous in self._pending_patches:
                remaining = {key: value for key, value in previous.items() if key not in patch}
                if remaining:
                    pending.append((version, remaining))
            self._pending_patches = pending
            self._pending_patches.append((self._settings.version, patch.copy()))
            self.feedback.setText(self._t("saving"))
            self.feedback.setProperty("tone", "checking")
            refresh_style(self.feedback)
            logger.info("ui.preferences_requested", extra={"fields": {"changed_fields": list(patch)}})
            self.preferences_changed.emit(patch)

    def _browse(self, key, kind):
        initial = self.fields[key].text().strip() or str(Path.home())
        if kind == "folder":
            chosen = QFileDialog.getExistingDirectory(self, tr("output", self._language), initial)
        else:
            file_filter = "CANoe configuration (*.cfg)" if kind == "cfg" else "Programs (*.exe);;All files (*)"
            chosen, _ = QFileDialog.getOpenFileName(self, tr("browse", self._language), initial, file_filter)
        if chosen:
            self.fields[key].setText(chosen)
            self._save_preferences((key,), force=True)

    def _format_changed(self, _value):
        self._mark_dirty("ethernet_format")
        self._save_preferences(("ethernet_format",))

    def _buffer_changed(self, _index):
        self._mark_dirty("ethernet_buffer_mib")
        self._save_preferences(("ethernet_buffer_mib",))

    def _nic_changed(self, _index):
        self._mark_dirty("nic_id")
        self._save_preferences(("nic_id",))

    def _apply(self):
        if self._busy:
            return
        index = self.fields["next_index"].text().strip()
        try:
            next_index = parse_index(index)
        except NamingError:
            self.set_error(tr("invalid_index", self._language))
            return
        values = {key: self._current(key) for key in self.fields}
        values.update(next_index=next_index, nic_id=self._current("nic_id"),
                      ethernet_format=self.format_input.currentText(),
                      ethernet_buffer_mib=self._current("ethernet_buffer_mib"))
        self._save_preferences(PREFERENCES)
        self.feedback.clear()
        self.settings_applied.emit(replace(self._settings, **values))

    def _prepare(self, role):
        if self._busy or role in self._preparing:
            return
        self.set_preparation_report({"role": role.value, "status": "checking",
            "message_ko": "연결을 확인하고 있습니다…", "message_en": "Checking the connection…", "detail": ""})
        self._save_preferences(PREFERENCES, force=True)
        self.prepare_requested.emit(role)

    def set_settings(self, settings):
        if settings.version < self._settings.version:
            return
        while self._pending_patches:
            version, patch = self._pending_patches[0]
            if settings.version < version or any(getattr(settings, key) != value for key, value in patch.items()):
                break
            self._pending_patches.popleft()
        pending = {key for _, patch in self._pending_patches for key in patch}
        self._settings = settings
        self._updating = True
        try:
            for key, field in self.fields.items():
                value = str(getattr(settings, key))
                if key in self._dirty:
                    if self._current(key) != value or key in pending:
                        continue
                    self._dirty.discard(key)
                with QSignalBlocker(field):
                    field.setText(value)
                    field.setToolTip(value)
            for key, combo in self.block_inputs.items():
                value = getattr(settings, key)
                if key in self._dirty and (self._current(key) != value or key in pending):
                    continue
                self._dirty.discard(key)
                with QSignalBlocker(combo):
                    index = combo.findData(value)
                    if index < 0:
                        combo.addItem(f"Logging {value}", value)
                        index = combo.count() - 1
                    combo.setCurrentIndex(index)
            if "ethernet_format" not in self._dirty or (
                self._current("ethernet_format") == settings.ethernet_format and "ethernet_format" not in pending
            ):
                self._dirty.discard("ethernet_format")
                with QSignalBlocker(self.format_input):
                    self.format_input.setCurrentText(settings.ethernet_format)
            selected = self._current("nic_id") if "nic_id" in self._dirty else settings.nic_id
            key = "ethernet_buffer_mib"
            if key not in self._dirty or (self._current(key) == settings.ethernet_buffer_mib and key not in pending):
                self._dirty.discard(key)
                with QSignalBlocker(self.buffer_input):
                    index = self.buffer_input.findData(settings.ethernet_buffer_mib)
                    if index < 0:
                        self.buffer_input.addItem(f"{settings.ethernet_buffer_mib} MiB", settings.ethernet_buffer_mib)
                        index = self.buffer_input.count() - 1
                    self.buffer_input.setCurrentIndex(index)
            if selected == settings.nic_id and "nic_id" not in pending:
                self._dirty.discard("nic_id")
            self._render_networks(selected)
        finally:
            self._updating = False
        self.set_language(settings.language)
        if not self._pending_patches and self.feedback.property("tone") == "checking":
            self.feedback.setText(self._t("saved"))
            self.feedback.setProperty("tone", "ready")
            refresh_style(self.feedback)

    def _request_discovery(self, *, reset_tool=False):
        if self._discovering:
            return
        self._discovery_started = self._discovering = True
        self._discovery_revision = self._revision
        self.set_discovery_busy(True)
        self.discovery_requested.emit(reset_tool)

    def set_discovery_busy(self, busy: bool):
        self._discovering = busy
        if busy:
            self._discovery_error = ""
            self._discovery_timer.start()
        else:
            self._discovery_timer.stop()
        self.find_button.setEnabled(not self._busy and not busy)
        self._render_discovery()

    def _discovery_timed_out(self):
        logger.warning("ui.discovery_response_timeout")
        self.set_discovery_error(self._t("timeout"))

    def set_discovery_error(self, message: str):
        self._discovery_error = message
        self.set_discovery_busy(False)

    def open_section(self, section: str):
        self.tabs.setCurrentIndex({"storage": 0, "canoe": 1, "ethernet": 2}.get(section, 0))
        self.show()
        self.raise_()
        self.activateWindow()

    def set_connection_discovery(self, report):
        self._discovery = report
        self._discovery_started = True
        self._discovery_error = ""
        self.set_discovery_busy(False)
        tool = report.get("tshark", {})
        if not self._busy and tool.get("path") and tool.get("status") == "ready" and not self._current("tshark_path") and (
            self._field_revision.get("tshark_path", 0) <= self._discovery_revision
        ):
            self.fields["tshark_path"].setText(tool["path"])
            self._save_preferences(("tshark_path",), force=True)
        self._render_networks(self._current("nic_id") if "nic_id" in self._dirty else self._settings.nic_id)
        self._render_discovery()

    def _render_networks(self, selected):
        with QSignalBlocker(self.nic_input):
            self.nic_input.clear()
            self.nic_input.addItem(self._t("choose_network"), "")
            for item in self._discovery.get("interfaces", []):
                identifier = str(item.get("id", ""))
                if not identifier:
                    continue
                name = item.get("name") or item.get("description") or self._t("network")
                status = item.get("status", "unknown")
                display = f"{name} · {self._t(status if status in {'up', 'down', 'unknown'} else 'unknown')}"
                description = item.get("description", "")
                if description and description != name:
                    display += " · " + description
                if not item.get("capture_available", False):
                    display += " · " + self._t("capture_attention")
                self.nic_input.addItem(display, identifier)
                self.nic_input.setItemData(self.nic_input.count() - 1,
                    "\n".join(filter(None, (name, description, item.get("mac", ""), identifier))), Qt.ItemDataRole.ToolTipRole)
            index = self.nic_input.findData(selected)
            if selected and index < 0:
                self.nic_input.addItem(self._t("missing_network"), selected)
                index = self.nic_input.count() - 1
                self.nic_input.setItemData(index, selected, Qt.ItemDataRole.ToolTipRole)
            self.nic_input.setCurrentIndex(max(index, 0))

    def _render_discovery(self):
        tool = self._discovery.get("tshark", {})
        message = tool.get("message_" + self._language) or self._t(
            "tool_found" if tool.get("status") == "ready" else "tool_missing" if tool else "tool_pending")
        if tool.get("version"):
            message += "\n" + str(tool["version"]).splitlines()[0]
        if tool and tool.get("status") != "ready":
            message += "\n" + self._t("tool_next")
        self.tool_status.setText(self._t("finding") if self._discovering else self._discovery_error or message)
        self.tool_status.setToolTip(str(tool.get("detail", "")))
        self.tool_status.setProperty("tone", "checking" if self._discovering else "error" if self._discovery_error else
                                     "ready" if tool.get("status") == "ready" else "attention")
        refresh_style(self.tool_status)
        driver = self._discovery.get("npcap", {})
        missing = driver.get("status") == "missing"
        self.driver_status.setText(self._t("npcap_help") if missing else driver.get("message_" + self._language, ""))
        self.driver_status.setProperty("tone", "attention" if missing else "neutral")
        refresh_style(self.driver_status)
        self.npcap_button.setVisible(missing)

    def set_preparation_report(self, report):
        try:
            role = Role(report["role"])
        except (KeyError, ValueError):
            logger.warning("ui.preparation_report_invalid")
            return
        self._reports[role] = dict(report)
        if role != Role.ETHERNET and "blocks" in report:
            key = ("can" if role == Role.CAN else "diag") + "_logging_block"
            combo = self.block_inputs[key]
            selected = self._current(key) if key in self._dirty else report.get("selected_block", "")
            with QSignalBlocker(combo):
                combo.clear()
                combo.addItem("기록 블록 선택" if self._language == "ko" else "Choose logging block", "")
                for item in report["blocks"]:
                    label = f"{item['id']} · {item['name']}"
                    if item.get("format"):
                        label += f" · .{item['format']}"
                    if item.get("compatible") is False:
                        label += " · 선택 불가" if self._language == "ko" else " · unavailable"
                    combo.addItem(label, item["id"])
                    index = combo.count() - 1
                    combo.setItemData(index, item.get("path", ""), Qt.ItemDataRole.ToolTipRole)
                    if item.get("compatible") is False:
                        combo.model().item(index).setEnabled(False)
                combo.setCurrentIndex(max(0, combo.findData(selected)))
        if report.get("status") == "checking":
            self._preparing.add(role)
        else:
            self._preparing.discard(role)
        self._render_preparation(role)
        if self.isVisible():
            # Results can expand a card after the worker finishes. Keep the
            # clicked card in view even at the minimum supported window height.
            QTimer.singleShot(0, lambda r=role: self._scroll_to_result(r))

    def _scroll_to_result(self, role):
        index = 2 if role == Role.ETHERNET else 1
        if self.tabs.currentIndex() == index:
            self.tabs.widget(index).ensureWidgetVisible(self._preparation_cards[role], 0, 12)

    def _render_preparation(self, role):
        report = self._reports.get(role, {})
        status = report.get("status", "neutral")
        title = self._t(status) if status in {"checking", "ready", "attention", "error"} else self._t("unprepared")
        message = report.get("message_" + self._language, "")
        label = self.target_labels[role]
        label.setText(title + (" · " + message if message else ""))
        label.setProperty("tone", status)
        refresh_style(label)
        detail = str(report.get("detail", ""))
        visible_detail = detail[:500] if status in {"attention", "error"} else ""
        self.result_details[role].setText(visible_detail)
        self.result_details[role].setVisible(bool(visible_detail))
        self.result_details[role].setToolTip(detail)
        action = report.get("next_action_" + self._language, "")
        if report and not action:
            action = self._t("wait" if status == "checking" else "ready_next" if status == "ready" else
                             "network_next" if role == Role.ETHERNET else "cfg_next")
        self.next_actions[role].setText(action)
        self.next_actions[role].setVisible(bool(action))
        self.prepare_buttons[role].setText(self._t("checking" if role in self._preparing else "check"))
        self.prepare_buttons[role].setEnabled(not self._busy and role not in self._preparing)

    def set_target(self, target):
        self.targets[target.role] = target
        state = target.connection.value
        if state == "connecting":
            self.set_preparation_report({"role": target.role.value, "status": "checking", "detail": target.evidence})
        elif state in {"ready", "error", "unknown"}:
            previous = self._reports.get(target.role, {})
            if previous.get("status") not in {"ready", "error", "attention"} or target.role in self._preparing:
                self.set_preparation_report({"role": target.role.value,
                    "status": "ready" if state == "ready" else "error" if state == "error" else "attention",
                    "detail": target.evidence})
        self._render_preparation(target.role)

    def set_language(self, language):
        self._language = "en" if language == "en" else "ko"
        self.setWindowTitle(f"{tr('settings', self._language)} · AutoLog {__version__}")
        self.heading.setText(tr("settings", self._language))
        self.hint.setText(tr("locked", self._language) if self._busy else self._t("intro"))
        for index, key in enumerate(("storage", "canoe", "ethernet")):
            self.tabs.setTabText(index, self._t(key))
        for label in self.labels.values():
            label.setText(tr(label.property("translationKey"), self._language))
        for button in self.browse_buttons:
            button.setText(self._t("select") if button.property("picker") == "tool" else tr("browse", self._language))
        for label, key in ((self.naming_hint, "naming_help"), (self.can_hint, "can_help"),
                           (self.tool_heading, "tool"), (self.tool_hint, "tool_help"),
                           (self.network_label, "network"), (self.network_hint, "network_help"),
                           (self.scope_hint, "scope")):
            label.setText(self._t(key))
        self.format_label.setText(tr("format", self._language))
        self.buffer_label.setText("캡처 버퍼" if self._language == "ko" else "Capture buffer")
        self.buffer_hint.setText(
            "기본 64 MiB · 드라이버에 요청하는 버퍼입니다. 실제 적용량과 무손실 캡처를 보장하지 않습니다."
            if self._language == "ko" else
            "Default 64 MiB · Requested driver buffer; actual allocation and lossless capture are not guaranteed.")
        self.canoe_setup_button.setText("CANoe 독립 연결 설정…" if self._language == "ko" else
                                        "CANoe independent connection setup…")
        self.format_input.setToolTip(self._t("format_help"))
        self.find_button.setText(self._t("find"))
        for key, label in self.block_labels.items():
            label.setText("기록 블록" if self._language == "ko" else "Logging Block")
            self.block_inputs[key].setItemText(0, "연결 후 블록 선택" if self._language == "ko" else "Choose block after connection")
        self.install_button.setText("Wireshark " + ("설치·복구" if self._language == "ko" else "install / repair"))
        self.npcap_button.setText(self._t("npcap"))
        for button, key in ((self.environment_button, "environment"), (self.exit_button, "exit"),
                            (self.apply_button, "apply"), (self.close_button, "close")):
            button.setText(tr(key, self._language))
        self._render_networks(self._current("nic_id") if "nic_id" in self._dirty else self._settings.nic_id)
        self._render_discovery()
        for role in Role:
            self._render_preparation(role)

    def set_busy(self, busy):
        self._busy = busy
        for widget in [*self.fields.values(), *self.browse_buttons, self.nic_input,
                       *self.block_inputs.values(), self.canoe_setup_button, self.format_input,
                       self.buffer_input, self.apply_button]:
            widget.setEnabled(not busy)
        self.find_button.setEnabled(not busy and not self._discovering)
        self.set_language(self._language)

    def set_error(self, message):
        if message:
            self._pending_patches.clear()
        self.feedback.setText(message)
        self.feedback.setProperty("tone", "error" if message else "ready")
        refresh_style(self.feedback)
