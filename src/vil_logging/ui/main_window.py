"""Compact control panel with request-only signals to application services."""

import logging
from collections import deque
from math import cos, pi, sin
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QPushButton,
    QStyle,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from vil_logging import __version__
from vil_logging.contracts.models import (
    AppEvent,
    AppSettings,
    PacketSummary,
    Role,
    SessionPhase,
    TargetSnapshot,
)
from vil_logging.storage.naming import capture_prefix

from .file_manager_dialog import FileManagerDialog, confirm_delete
from .i18n import render_event, tr
from .packet_window import PacketWindow
from .recovery_dialog import RecoveryDialog
from .settings_dialog import SettingsDialog
from .theme import COLOR, STYLE, ThemedCheckBox, apply_theme, refresh_style

logger = logging.getLogger(__name__)

BUSY_PHASES = {
    SessionPhase.PREPARING,
    SessionPhase.STARTING,
    SessionPhase.RECORDING,
    SessionPhase.PARTIAL,
    SessionPhase.STOPPING,
}
LOCKED_PHASES = BUSY_PHASES | {SessionPhase.INCOMPLETE}

MAIN_STYLE = """
QPushButton#loggingButton { color: #FFFFFF; background: #4263EB; border: 1px solid #4263EB;
    border-radius: 10px; font-size: 18px; font-weight: 700; padding: 0;
    min-height: 50px; max-height: 50px; }
QPushButton#loggingButton:hover { background: #3455D8; border-color: #3455D8; }
QPushButton#loggingButton:focus { border: 2px solid #92A5FF; padding: 0; }
QPushButton#loggingButton:disabled { background: #A6B5E7; border-color: #A6B5E7; }
QPushButton#loggingButton[recording="true"] { background: #B63B4A; border-color: #B63B4A; }
QFrame#targetCard QCheckBox { font-size: 13px; font-weight: 700; }
QLabel#captureFilenames { font-size: 13px; font-weight: 700; }
QLabel#readinessSubtitle { font-size: 12px; color: #64748B; }
QLabel#debugStatusLabel { font-size: 10px; color: #718198; }
"""


def _label(text: str = "", variant: str = "") -> QLabel:
    label = QLabel(text)
    if variant:
        label.setProperty("variant", variant)
    return label


def settings_icon() -> QIcon:
    """Draw a small gear without depending on a particular font's symbol coverage."""
    canvas = QPixmap(24, 24)
    canvas.fill(Qt.GlobalColor.transparent)
    path = QPainterPath()
    first_point = True
    for tooth in range(8):
        for offset, radius in ((-0.32, 6.8), (-0.19, 9.5), (0.19, 9.5), (0.32, 6.8)):
            angle = tooth * pi / 4 + offset
            x, y = 12 + radius * cos(angle), 12 + radius * sin(angle)
            if first_point:
                path.moveTo(x, y)
                first_point = False
            else:
                path.lineTo(x, y)
    path.closeSubpath()
    path.addEllipse(8.8, 8.8, 6.4, 6.4)
    path.setFillRule(Qt.FillRule.OddEvenFill)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.fillPath(path, QColor("#68768a"))
    painter.end()
    return QIcon(canvas)


class MainWindow(QMainWindow):
    logging_requested = Signal()
    bug_report_requested = Signal()
    settings_applied = Signal(object)
    preferences_changed = Signal(object)
    prepare_requested = Signal(object)
    discovery_requested = Signal(bool)
    npcap_requested = Signal()
    exit_requested = Signal()
    environment_requested = Signal()
    open_debug_folder_requested = Signal()
    rename_requested = Signal(str, str)
    delete_files_requested = Signal(object)
    files_refresh_requested = Signal()
    recovery_requested = Signal(object)

    def __init__(self, demo: bool = False):
        super().__init__()
        self.demo = demo
        self._settings = AppSettings()
        self._language = "ko"
        self._phase = SessionPhase.IDLE
        self._events: deque[AppEvent] = deque(maxlen=500)
        self._targets = {role: TargetSnapshot(role) for role in Role}
        self._files: list[str] = []
        self._files_label = ""
        self._debug_path = ""
        self._debug_error = ""
        self._capture_history = []
        self._file_busy = False
        self._last_file_result = None
        self._recovery_report = {}
        self._preparation_report: dict = {}
        self._discovery_report: dict = {}
        self.setObjectName("mainWindow")
        self.setFixedWidth(480)
        apply_theme(self)
        self.setStyleSheet(STYLE + MAIN_STYLE)
        self.setWindowIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 15, 18, 14)
        outer.setSpacing(9)
        header = QHBoxLayout()
        header.setSpacing(5)
        self.eyebrow = _label(f"AUTOLOG / LOGGING CONTROL · {__version__}", "eyebrow")
        header.addWidget(self.eyebrow, 1)
        self.bug_report_button = QPushButton()
        self.bug_report_button.setObjectName("bugReportButton")
        self.bug_report_button.setProperty("compact", True)
        self.bug_report_button.clicked.connect(self.bug_report_requested)
        header.addWidget(self.bug_report_button)
        self.language_group = QButtonGroup(self)
        self.language_group.setExclusive(True)
        self.language_buttons: dict[str, QToolButton] = {}
        for language, text in (("ko", "한국어"), ("en", "EN")):
            button = QToolButton()
            button.setText(text)
            button.setCheckable(True)
            button.setObjectName(f"language{language.upper()}Button")
            button.setProperty("compact", True)
            button.clicked.connect(lambda _checked=False, lang=language: self._change_language(lang))
            self.language_group.addButton(button)
            self.language_buttons[language] = button
            header.addWidget(button)
        self.settings_button = QToolButton()
        self.settings_button.setIcon(settings_icon())
        self.settings_button.setIconSize(QSize(20, 20))
        self.settings_button.setObjectName("settingsButton")
        self.settings_button.setProperty("compact", True)
        self.settings_button.clicked.connect(self._show_settings)
        header.addWidget(self.settings_button)
        outer.addLayout(header)
        title_row = QHBoxLayout()
        self.title_label = _label(variant="title")
        title_row.addWidget(self.title_label, 1)
        self.status_pill = _label(variant="status")
        self.status_pill.setProperty("tone", "neutral")
        title_row.addWidget(self.status_pill)
        outer.addLayout(title_row)
        self.subtitle = _label(variant="muted")
        self.subtitle.setObjectName("readinessSubtitle")
        self.subtitle.setWordWrap(True)
        self.subtitle.setMinimumHeight(32)
        outer.addWidget(self.subtitle)
        self.demo_label = _label(variant="status")
        self.demo_label.setProperty("tone", "attention")
        self.demo_label.setWordWrap(True)
        self.demo_label.setVisible(demo)
        outer.addWidget(self.demo_label)
        target_heading = QHBoxLayout()
        self.target_heading = _label(variant="section")
        self.selection_count = _label(variant="helper")
        target_heading.addWidget(self.target_heading, 1)
        target_heading.addWidget(self.selection_count)
        outer.addLayout(target_heading)
        cards = QHBoxLayout()
        cards.setSpacing(8)
        self.role_checks: dict[Role, QCheckBox] = {}
        self.target_states: dict[Role, QLabel] = {}
        self.observation_labels: dict[Role, QLabel] = {}
        self.target_formats: dict[Role, QLabel] = {}
        self._role_cards: dict[Role, QFrame] = {}
        for role in Role:
            card = QFrame()
            card.setObjectName("targetCard")
            card.setProperty("role", "card")
            card.setProperty("selected", role == Role.ETHERNET)
            self._role_cards[role] = card
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 11, 8, 10)
            card_layout.setSpacing(7)
            card_top = QHBoxLayout()
            card_top.setSpacing(3)
            check = ThemedCheckBox(role.label)
            check.setObjectName(f"select{role.label}CheckBox")
            check.setChecked(role == Role.ETHERNET)
            check.toggled.connect(self._selection_changed)
            self.role_checks[role] = check
            card_top.addWidget(check, 1)
            format_label = _label(variant="helper")
            self.target_formats[role] = format_label
            card_top.addWidget(format_label)
            card_layout.addLayout(card_top)
            state = _label(variant="status")
            state.setObjectName(f"state{role.label}Label")
            state.setWordWrap(True)
            self.target_states[role] = state
            card_layout.addWidget(state)
            observation = _label(variant="helper")
            observation.setWordWrap(True)
            self.observation_labels[role] = observation
            card_layout.addWidget(observation)
            cards.addWidget(card, 1)
        outer.addLayout(cards)
        self.logging_button = QPushButton("logging")
        self.logging_button.setObjectName("loggingButton")
        self.logging_button.setFixedHeight(52)
        self.logging_button.clicked.connect(self.logging_requested)
        outer.addWidget(self.logging_button)
        self.phase_label = _label(variant="helper")
        self.phase_label.setWordWrap(True)
        self.phase_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self.phase_label)
        self.recovery_button = QPushButton()
        self.recovery_button.setObjectName("openRecoveryButton")
        self.recovery_button.setProperty("compact", True)
        self.recovery_button.clicked.connect(self._show_recovery)
        self.recovery_button.hide()
        outer.addWidget(self.recovery_button)
        file_frame = QFrame()
        file_frame.setObjectName("filePanel")
        file_frame.setProperty("panel", True)
        file_layout = QVBoxLayout(file_frame)
        file_layout.setContentsMargins(12, 9, 12, 11)
        file_layout.setSpacing(7)
        file_top = QHBoxLayout()
        self.file_heading = _label(variant="section")
        self.file_heading.setWordWrap(True)
        file_top.addWidget(self.file_heading, 1)
        self.file_manager_button = QPushButton()
        self.file_manager_button.setProperty("compact", True)
        self.file_manager_button.clicked.connect(self._show_file_manager)
        file_top.addWidget(self.file_manager_button)
        self.delete_button = QPushButton()
        self.delete_button.setObjectName("deletePreviousButton")
        self.delete_button.setProperty("variant", "ghost")
        self.delete_button.setProperty("compact", True)
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self._delete_previous)
        file_top.addWidget(self.delete_button)
        file_layout.addLayout(file_top)
        self.file_names = QLabel()
        self.file_names.setObjectName("captureFilenames")
        self.file_names.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.file_names.setWordWrap(True)
        self.file_names.setMinimumHeight(25)
        file_layout.addWidget(self.file_names)
        self.output_label = _label(variant="helper")
        file_layout.addWidget(self.output_label)
        rename_row = QHBoxLayout()
        self.previous_name = QLineEdit()
        self.previous_name.setObjectName("previousNameInput")
        self.previous_name.setEnabled(False)
        rename_row.addWidget(self.previous_name, 1)
        self.rename_button = QPushButton()
        self.rename_button.setObjectName("renamePreviousButton")
        self.rename_button.setEnabled(False)
        self.rename_button.clicked.connect(self._rename_previous)
        rename_row.addWidget(self.rename_button)
        file_layout.addLayout(rename_row)
        self.file_feedback = _label(variant="helper")
        self.file_feedback.setWordWrap(True)
        self.file_feedback.setFixedHeight(32)
        file_layout.addWidget(self.file_feedback)
        outer.addWidget(file_frame)
        event_row = QHBoxLayout()
        self.event_heading = _label(variant="section")
        self.event_count = _label(variant="helper")
        event_row.addWidget(self.event_heading, 1)
        event_row.addWidget(self.event_count)
        outer.addLayout(event_row)
        self.event_list = QListWidget()
        self.event_list.setObjectName("eventList")
        self.event_list.setWordWrap(True)
        self.event_list.setFixedHeight(108)
        self.event_list.setAccessibleName("Notifications and capture events")
        self.event_empty = _label(variant="helper")
        self.event_empty.setParent(self.event_list.viewport())
        self.event_empty.setGeometry(8, 31, 410, 24)
        self.event_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.event_empty.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        outer.addWidget(self.event_list)
        footer_controls = QHBoxLayout()
        self.packet_button = QPushButton()
        self.packet_button.setObjectName("openPacketsButton")
        self.packet_button.clicked.connect(self._show_packets)
        self.debug_folder_button = QPushButton()
        self.debug_folder_button.setObjectName("openDebugFolderButton")
        self.debug_folder_button.clicked.connect(self.open_debug_folder_requested)
        self.debug_folder_button.setEnabled(False)
        self.environment_button = QPushButton()
        self.environment_button.clicked.connect(self.environment_requested)
        for button in (self.packet_button, self.debug_folder_button, self.environment_button):
            button.setProperty("compact", True)
            footer_controls.addWidget(button)
        outer.addLayout(footer_controls)
        self.debug_status = _label(variant="helper")
        self.debug_status.setObjectName("debugStatusLabel")
        self.debug_status.setWordWrap(True)
        outer.addWidget(self.debug_status)
        self.footer = _label(variant="helper")
        self.footer.setWordWrap(True)
        self.footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self.footer)
        self.settings_dialog = SettingsDialog(self)
        self.settings_dialog.settings_applied.connect(self.settings_applied)
        if hasattr(self.settings_dialog, "preferences_changed"):
            self.settings_dialog.preferences_changed.connect(self.preferences_changed)
        if hasattr(self.settings_dialog, "discovery_requested"):
            self.settings_dialog.discovery_requested.connect(self.discovery_requested)
        self.settings_dialog.prepare_requested.connect(self.prepare_requested)
        self.settings_dialog.npcap_requested.connect(self.npcap_requested)
        self.settings_dialog.environment_requested.connect(self.environment_requested)
        self.settings_dialog.exit_requested.connect(self.exit_requested)
        self.packet_window = PacketWindow(self)
        self.file_manager = FileManagerDialog(self)
        self.file_manager.delete_requested.connect(self.delete_files_requested)
        self.file_manager.refresh_requested.connect(self.files_refresh_requested)
        self.file_manager.recovery_requested.connect(self._show_recovery)
        self.recovery_dialog = RecoveryDialog(self)
        self.recovery_dialog.requested.connect(self.recovery_requested)
        self.tray: QSystemTrayIcon | None = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.windowIcon(), self)
            self.tray_menu = QMenu(self)
            self.show_action = QAction(self)
            self.show_action.triggered.connect(self._restore)
            self.exit_action = QAction(self)
            self.exit_action.triggered.connect(self.exit_requested)
            self.tray_menu.addAction(self.show_action)
            self.tray_menu.addSeparator()
            self.tray_menu.addAction(self.exit_action)
            self.tray.setContextMenu(self.tray_menu)
            self.tray.activated.connect(self._tray_activated)
            self.tray.show()
        self.set_settings(self._settings)
        self.set_phase(SessionPhase.IDLE)
        self.set_debug_status()

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._restore()

    def _restore(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def restore_window(self):
        """Restore the panel when a second application launch activates this instance."""
        self._restore()

    def _show_settings(self):
        logger.debug("Opening settings editor; phase=%s", self._phase.value)
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def _show_packets(self):
        logger.debug("Opening packet display; retained_packets=%s", len(self.packet_window.packets))
        self.packet_window.show()
        self.packet_window.raise_()

    def _change_language(self, language: str):
        logger.debug("Display language requested: %s", language)
        self.set_language(language)
        self.preferences_changed.emit({"language": language})

    def set_language(self, language: str):
        self._language = "en" if language == "en" else "ko"
        language = self._language
        self.setWindowTitle(f"AutoLog · {tr('title', language)} · {__version__}")
        self.title_label.setText(tr("title", language))
        self.demo_label.setText(tr("demo", language))
        self.language_buttons[language].setChecked(True)
        self.settings_button.setToolTip(tr("settings", language))
        self.settings_button.setAccessibleName(tr("settings", language))
        self.delete_button.setText(tr("delete", language))
        self.file_manager_button.setText(tr("file_manager", language))
        help_key = "demo_file_ops" if self.demo else "file_ops_help"
        self.delete_button.setToolTip(tr(help_key, language))
        self.rename_button.setText(tr("rename", language))
        self.rename_button.setToolTip(tr(help_key, language))
        self.previous_name.setPlaceholderText(tr("previous_name", language))
        self.previous_name.setToolTip(tr(help_key, language))
        self.file_feedback.setText(tr(help_key, language))
        if self._last_file_result:
            self.set_file_result(self._last_file_result)
        self.event_heading.setText(tr("events", language))
        self.event_empty.setText(tr("events_empty", language))
        self.target_heading.setText(tr("capture_targets", language))
        self.bug_report_button.setText(tr("bug_report", language))
        self.packet_button.setText(tr("packets", language))
        self.debug_folder_button.setText(tr("debug_folder", language))
        self.environment_button.setText(tr("environment", language))
        self.footer.setText(tr("demo", language) if self.demo else
                            tr("ethernet_stage", language) + "\n" + tr("real", language))
        self.settings_dialog.set_language(language)
        self.packet_window.set_language(language)
        self.file_manager.set_language(language)
        self.recovery_dialog.set_language(language)
        self.set_recovery(self._recovery_report)
        if self.tray:
            self.show_action.setText(tr("show", language))
            self.exit_action.setText(tr("exit", language))
            self.tray.setToolTip(self.windowTitle())
        self._render_files()
        self._render_events()
        self._render_debug()
        for target in self._targets.values():
            self.set_target(target)
        self.set_phase(self._phase)

    def set_settings(self, settings: AppSettings):
        self._settings = settings
        self.settings_dialog.set_settings(settings)
        self.set_language(settings.language)

    def selected_roles(self) -> tuple[Role, ...]:
        return tuple(role for role, check in self.role_checks.items() if check.isChecked())

    def _selection_changed(self, *_):
        logger.debug("Capture selection changed: %s", [role.value for role in self.selected_roles()])
        self._render_files()
        self.set_phase(self._phase)

    def set_connection_discovery(self, report: dict):
        """Forward discovery results to the settings view without touching external tools."""
        self._discovery_report = dict(report)
        if hasattr(self.settings_dialog, "set_connection_discovery"):
            self.settings_dialog.set_connection_discovery(report)

    def set_preparation_report(self, report: dict):
        """Display the most recent preparation action in the current display language."""
        self._preparation_report = dict(report)
        if hasattr(self.settings_dialog, "set_preparation_report"):
            self.settings_dialog.set_preparation_report(report)
        self._render_readiness()

    def _render_readiness(self):
        count = len(self.selected_roles())
        self.selection_count.setText(tr("selected_count", self._language).format(count=count))
        for role, card in self._role_cards.items():
            card.setProperty("selected", self.role_checks[role].isChecked())
            refresh_style(card)
        tone = "neutral"
        if self._phase in (SessionPhase.RECORDING, SessionPhase.COMPLETED):
            tone = "ready"
        elif self._phase in (SessionPhase.PREPARING, SessionPhase.STARTING, SessionPhase.STOPPING):
            tone = "checking"
        elif self._phase in (SessionPhase.FAILED, SessionPhase.INCOMPLETE):
            tone = "error"
        elif self._phase == SessionPhase.PARTIAL:
            tone = "attention"
        self.status_pill.setProperty("tone", tone)
        self.status_pill.setText(tr("phase_short_" + self._phase.value, self._language))
        refresh_style(self.status_pill)
        action = "action_unprepared"
        if self._phase in BUSY_PHASES:
            action = "action_" + self._phase.value
        elif self._phase == SessionPhase.INCOMPLETE:
            action = "action_incomplete"
        elif self._phase == SessionPhase.COMPLETED:
            action = "action_completed"
        elif self._phase == SessionPhase.FAILED:
            action = "action_failed"
        elif not count:
            action = "action_no_targets"
        elif all(self._targets[role].connection.value == "ready" for role in self.selected_roles()):
            action = "action_ready"
        message = tr(action, self._language)
        if self.demo and self._phase == SessionPhase.COMPLETED:
            message = tr("demo_completed", self._language)
        if self._preparation_report and self._phase == SessionPhase.IDLE:
            message = self._preparation_report.get("message_" + self._language) or message
        self.subtitle.setText(message)
        self.subtitle.setToolTip(str(self._preparation_report.get("detail", message)))

    def set_phase(self, phase: SessionPhase):
        if self._phase != phase:
            logger.debug("UI phase transition: %s -> %s", self._phase.value, phase)
        self._phase = SessionPhase(phase)
        phase = self._phase
        busy = phase in LOCKED_PHASES or self._file_busy
        for check in self.role_checks.values():
            check.setEnabled(not busy)
            check.setToolTip(tr("locked" if busy else "ready_tip", self._language))
        for button in self.language_buttons.values():
            button.setEnabled(not busy)
        self.settings_dialog.set_busy(busy)
        self.logging_button.setEnabled(
            not self._file_busy and phase not in (SessionPhase.STOPPING, SessionPhase.INCOMPLETE)
            and (busy or bool(self.selected_roles()))
        )
        self.logging_button.setProperty("recording", phase in (SessionPhase.RECORDING, SessionPhase.PARTIAL))
        self.logging_button.style().unpolish(self.logging_button)
        self.logging_button.style().polish(self.logging_button)
        phase_key = (
            "demo_" + phase.value
            if self.demo and phase in (
                SessionPhase.COMPLETED, SessionPhase.RECORDING, SessionPhase.PARTIAL
            )
            else phase.value
        )
        self.phase_label.setText(tr(phase_key, self._language))
        self.logging_button.setToolTip(tr(phase_key, self._language))
        self._render_readiness()
        self._render_file_controls()
        self.recovery_dialog.set_locked(self._file_busy or phase in BUSY_PHASES)

    def set_target(self, target: TargetSnapshot):
        if self._targets.get(target.role) != target:
            logger.debug("UI target updated: %r", target)
        self._targets[target.role] = target
        self.settings_dialog.set_target(target)
        active = target.recording.value not in ("idle", "stopped")
        value = target.recording.value if active else target.connection.value
        state = self.target_states[target.role]
        state_key = "phase_short_" + value if value in ("starting", "recording", "stopping") else value
        state.setText(tr(state_key, self._language))
        state.setToolTip(target.evidence)
        tone = (
            "error" if value in ("error", "unknown")
            else "ready" if value in ("recording", "ready")
            else "checking" if value in ("connecting", "starting", "stopping")
            else "neutral"
        )
        state.setProperty("tone", tone)
        refresh_style(state)
        self.observation_labels[target.role].setText(tr(target.observation.value, self._language))
        self.observation_labels[target.role].setToolTip(target.evidence)
        self.target_formats[target.role].setText(
            "." + self._settings.ethernet_format if target.role == Role.ETHERNET else ".blf"
        )
        self._render_readiness()

    def _render_files(self):
        if self._files:
            default_heading = "demo_files" if self.demo else "completed"
            heading_key = self._files_label or default_heading
            heading_key = {
                "recording": "current_files", "completed": "previous_files",
                "incomplete": "incomplete_files"
            }.get(heading_key, heading_key)
            self.file_heading.setText(tr(heading_key, self._language))
            self.file_names.setText(" · ".join(Path(path).name for path in self._files))
            self.file_names.setToolTip("\n".join(self._files))
        else:
            self.file_heading.setText(tr("next_files", self._language))
            names = []
            for role in self.selected_roles():
                prefix = capture_prefix(self._settings.prefix) + ("Diag_" if role == Role.DIAG else "")
                extension = self._settings.ethernet_format if role == Role.ETHERNET else "blf"
                names.append(f"{prefix}{self._settings.next_index}.{extension}")
            self.file_names.setText(" · ".join(names) or "—")
            self.file_names.setToolTip("\n".join(names))
        output = (str(Path(self._files[0]).parent) if self._files and Path(self._files[0]).is_absolute()
                  else self._settings.output_dir or tr("unset", self._language))
        output_text = f"{tr('output', self._language)}: {output}"
        self.output_label.setText(
            self.output_label.fontMetrics().elidedText(output_text, Qt.TextElideMode.ElideMiddle, 412)
        )
        self.output_label.setToolTip(output)

    def set_files(self, files: list[str], label: str = ""):
        self._files = list(files)
        self._files_label = label
        self._render_files()

    def set_capture_history(self, history: list[dict]):
        old = self._capture_history[0] if self._capture_history else {}
        latest = history[0] if history else {}
        self._capture_history = history
        self.file_manager.set_history(history)
        if ((old.get("session_id"), old.get("current_name")) !=
                (latest.get("session_id"), latest.get("current_name"))):
            self.previous_name.setText(latest.get("current_name", ""))
        self._render_file_controls()

    def set_file_busy(self, busy: bool):
        self._file_busy = busy
        if busy:
            self._last_file_result = None
            self.file_feedback.setText(tr("file_operation_busy", self._language))
        elif self._last_file_result:
            self.set_file_result(self._last_file_result)
        self.set_phase(self._phase)

    def _render_file_controls(self):
        locked = self.demo or self._file_busy or self._phase in LOCKED_PHASES
        latest = self._capture_history[0] if self._capture_history else {}
        ready = bool(latest.get("can_rename")) and not locked
        self.previous_name.setEnabled(ready)
        self.rename_button.setEnabled(ready)
        self.delete_button.setEnabled(ready)
        self.file_manager.set_locked(locked)

    def _rename_previous(self):
        if self.rename_button.isEnabled() and self._capture_history:
            self.rename_requested.emit(self._capture_history[0]["session_id"], self.previous_name.text())

    def _delete_previous(self):
        if self.delete_button.isEnabled() and self._capture_history:
            files = self._capture_history[0]["files"]
            if confirm_delete(files, self._language, self):
                self.delete_files_requested.emit(files)

    def _show_file_manager(self):
        self.files_refresh_requested.emit()
        self.file_manager.show()
        self.file_manager.raise_()

    def _show_recovery(self):
        self.files_refresh_requested.emit()
        self.recovery_dialog.show()
        self.recovery_dialog.raise_()
        self.recovery_dialog.activateWindow()

    def set_recovery(self, report):
        self._recovery_report = report
        count = len(report.get("sessions", [])) + len(report.get("operations", []))
        self.recovery_button.setText(tr("recovery_count", self._language).format(count=count))
        self.recovery_button.setVisible(bool(count) or bool(report.get("live_session_id")))
        self.recovery_dialog.set_report(report)

    def set_file_result(self, result: dict):
        self._last_file_result = result
        message = result.get("error") or tr("file_result_" + result["status"], self._language)
        self.file_feedback.setText(message.splitlines()[-1][:160])
        self.file_feedback.setToolTip(message)
        self.file_manager.set_result(result)

    def add_event(self, event: AppEvent):
        self._events.append(event)
        self._append_event_item(event)
        while self.event_list.count() > 500:
            self.event_list.takeItem(0)
        self.event_list.scrollToBottom()
        self.event_count.setText(tr("event_count", self._language).format(count=len(self._events)))
        self.event_empty.setVisible(not self._events)
        if event.code == "SETTINGS_ERROR":
            self.settings_dialog.set_error(render_event(event, self._language))
        elif event.code == "SETTINGS_SAVED":
            self.settings_dialog.set_error("")

    def _append_event_item(self, event: AppEvent):
        item = QListWidgetItem(render_event(event, self._language, include_details=False))
        item.setToolTip(f"{event.timestamp}\n{event.code}\n{render_event(event, self._language)}")
        color = {
            "ERROR": COLOR["error"], "CRITICAL": COLOR["error"], "WARNING": COLOR["attention"]
        }.get(event.level.upper(), COLOR["muted"])
        item.setForeground(QColor(color))
        self.event_list.addItem(item)

    def _render_events(self):
        self.event_list.clear()
        for event in self._events:
            self._append_event_item(event)
        if self.event_list.count():
            self.event_list.scrollToBottom()
        self.event_count.setText(tr("event_count", self._language).format(count=len(self._events)))
        self.event_empty.setVisible(not self._events)

    def set_debug_status(self, path: str = "", error: str = ""):
        self._debug_path = path
        self._debug_error = error
        self._render_debug()

    def _render_debug(self):
        help_text = tr("debug_help", self._language)
        if self._debug_path:
            help_text += "\n" + self._debug_path
        self.bug_report_button.setToolTip(help_text)
        self.bug_report_button.setEnabled(bool(self._debug_path))
        self.debug_folder_button.setToolTip(self._debug_path or help_text)
        self.debug_folder_button.setEnabled(bool(self._debug_path))
        text = tr("debug_on" if self._debug_path else "debug_off", self._language)
        if self._debug_path:
            text += f" · {Path(self._debug_path).name}"
        if self._debug_error:
            text += " · " + self._debug_error
        self.debug_status.setText(text)
        self.debug_status.setToolTip(help_text)
        self.debug_status.setVisible(bool(self._debug_error) or bool(self._debug_path))
        self.debug_status.setProperty("tone", "error" if self._debug_error else "neutral")
        refresh_style(self.debug_status)

    def add_packet(self, packet: PacketSummary):
        self.packet_window.add_packet(packet)

    def closeEvent(self, event):
        event.ignore()
        logger.debug("Main window close requested; requesting orderly application exit; phase=%s",
                     self._phase.value)
        self.exit_requested.emit()
