"""Receive evidence and editable Ethernet monitor criteria."""

from dataclasses import asdict
from uuid import uuid4

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from vil_logging.contracts.models import Role, TargetSnapshot
from vil_logging.monitors.rules import MAX_RULES, EthernetRule, encode_rules, parse_rules

from .i18n import tr
from .theme import ThemedComboBox, apply_theme

FIELDS = ("name", "protocol", "destination_ip", "destination_mac", "expected_ip", "expected_mac",
          "source_mac_prefix", "minimum_pps", "timeout_ms", "grace_ms", "max_delay_ms", "recovery_count")


def monitor_description(report, language):
    lines = []
    for reason in report.get("reasons", []):
        lines.append(tr("monitor_reason_" + reason, language))
    for row in report.get("rules", []):
        lines.append(row["name"] + " · " + tr(row["status"], language))
        lines.extend(tr("monitor_reason_" + reason, language) for reason in row["reasons"])
        if row.get("last_capture_utc"):
            lines.append(tr("monitor_last", language) + ": " + row["last_capture_utc"])
        lines.append(tr("monitor_counts", language).format(
            matched=row.get("matched_packets", 0), mismatched=row.get("mismatched_packets", 0)))
        if row.get("minimum_pps"):
            lines.append(tr("monitor_rate", language).format(rate=row.get("receive_pps", 0), minimum=row["minimum_pps"]))
        if row.get("last_mismatch_utc"):
            lines.append(tr("monitor_last_mismatch", language) + ": " + row["last_mismatch_utc"] +
                         " · " + row.get("last_mismatch_source", "") + " / " + row.get("last_mismatch_mac", ""))
    if "parsed_packets" in report:
        lines.append(tr("monitor_transport_counts", language).format(
            parsed=report["parsed_packets"], display=report.get("display_drops", 0),
            errors=report.get("parse_errors", 0)))
    return "\n".join(lines)


class MonitorDialog(QDialog):
    preferences_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("monitorDialog")
        self.resize(860, 650)
        self.setMinimumSize(720, 520)
        apply_theme(self)
        self._language = "ko"
        self._rules = []
        self._editing_id = ""
        self._locked = False
        self._updating = False
        self._drafts = {}
        self._document = None
        self._targets = {role: TargetSnapshot(role) for role in Role}
        layout = QVBoxLayout(self)
        self.help_label = QLabel()
        self.help_label.setWordWrap(True)
        layout.addWidget(self.help_label)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        status_page = QWidget()
        status_layout = QVBoxLayout(status_page)
        self.table = QTableWidget(0, 5)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().hide()
        for col in (0, 1):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        for col in (2, 3, 4):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        status_layout.addWidget(self.table, 1)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        status_layout.addWidget(self.details, 1)
        self.tabs.addTab(status_page, "")
        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        self.rules_hint = QLabel()
        self.rules_hint.setWordWrap(True)
        editor_layout.addWidget(self.rules_hint)
        rule_row = QHBoxLayout()
        self.rule_combo = ThemedComboBox()
        self.rule_combo.currentIndexChanged.connect(self._choose_rule)
        rule_row.addWidget(self.rule_combo, 1)
        self.new_button = QPushButton()
        self.new_button.clicked.connect(self._new_rule)
        rule_row.addWidget(self.new_button)
        self.delete_button = QPushButton()
        self.delete_button.clicked.connect(self._delete_rule)
        rule_row.addWidget(self.delete_button)
        editor_layout.addLayout(rule_row)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        form = QFormLayout(body)
        self.fields = {}
        self.labels = {}
        for key in FIELDS:
            field = QLineEdit()
            field.setObjectName("monitor_" + key)
            label = QLabel()
            self.fields[key], self.labels[key] = field, label
            form.addRow(label, field)
        scroll.setWidget(body)
        editor_layout.addWidget(scroll, 1)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setProperty("tone", "error")
        self.error_label.hide()
        editor_layout.addWidget(self.error_label)
        self.save_button = QPushButton()
        self.save_button.setProperty("variant", "primary")
        self.save_button.clicked.connect(self._save_rule)
        editor_layout.addWidget(self.save_button)
        self.tabs.addTab(editor, "")
        self.close_button = QPushButton()
        self.close_button.clicked.connect(self.close)
        layout.addWidget(self.close_button)
        self.set_language("ko")
        self._render_rules()

    def set_language(self, language):
        self._language = language
        self.setWindowTitle(tr("monitor_title", language))
        self.help_label.setText(tr("monitor_help", language))
        self.rules_hint.setText(tr("monitor_rules_help", language))
        self.tabs.setTabText(0, tr("monitor_status", language))
        self.tabs.setTabText(1, tr("monitor_rules", language))
        if self.rule_combo.count():
            self.rule_combo.setItemText(0, tr("monitor_new", language))
        self.table.setHorizontalHeaderLabels([tr(key, language) for key in (
            "monitor_target_rule", "file_state", "monitor_last", "source", "monitor_samples")])
        for key, label in self.labels.items():
            label.setText(tr("monitor_field_" + key, language))
            self.fields[key].setPlaceholderText(tr("monitor_optional" if key in {
                "protocol", "destination_ip", "destination_mac", "expected_ip", "expected_mac", "source_mac_prefix", "minimum_pps"}
                else "monitor_required", language))
        for button, key in ((self.new_button, "monitor_new"), (self.delete_button, "monitor_delete"),
                            (self.save_button, "monitor_save"), (self.close_button, "close")):
            button.setText(tr(key, language))
        self._render_status()

    def set_settings(self, settings):
        if settings.monitor_rules_json == self._document:
            return
        first_load = self._document is None
        self._document = settings.monitor_rules_json
        try:
            self._rules = list(parse_rules(self._document))
            self.set_error("")
        except (ValueError, TypeError) as error:
            self._rules = []
            self.set_error(str(error))
        self._drafts.clear()
        if first_load and self._rules:
            self._editing_id = self._rules[0].id
        self._render_rules()

    def _render_rules(self):
        self._updating = True
        self.rule_combo.clear()
        self.rule_combo.addItem(tr("monitor_new", self._language), "")
        for rule in self._rules:
            self.rule_combo.addItem(rule.name, rule.id)
        index = self.rule_combo.findData(self._editing_id)
        self.rule_combo.setCurrentIndex(max(index, 0))
        self._updating = False
        self._load_rule()
        self.set_locked(self._locked)

    def _choose_rule(self, *_):
        if not self._updating:
            self._drafts[self._editing_id] = {key: field.text() for key, field in self.fields.items()}
            self._load_rule()

    def _load_rule(self):
        self._editing_id = self.rule_combo.currentData() or ""
        rule = next((rule for rule in self._rules if rule.id == self._editing_id), None)
        values = self._drafts.get(self._editing_id, asdict(rule) if rule else {})
        for key, field in self.fields.items():
            field.setText(str(values.get(key, "")))
        self.delete_button.setEnabled(not self._locked and bool(rule))

    def _new_rule(self):
        self.rule_combo.setCurrentIndex(0)

    def _save_rule(self):
        if self._locked:
            return
        try:
            values = {key: field.text().strip() for key, field in self.fields.items()}
            values["minimum_pps"] = values["minimum_pps"] or "0"
            for key in ("timeout_ms", "grace_ms", "max_delay_ms", "recovery_count", "minimum_pps"):
                if not values[key] or not values[key].isascii() or not values[key].isdecimal() or len(values[key]) > 9:
                    raise ValueError(tr("monitor_field_" + key, self._language) + ": " + tr("monitor_integer", self._language))
                values[key] = int(values[key])
            identifier = self._editing_id or uuid4().hex
            rule = EthernetRule(id=identifier, **values)
            others = [rule for rule in self._rules if rule.id != identifier]
            if len(others) >= MAX_RULES:
                raise ValueError(tr("monitor_limit", self._language))
            document = encode_rules([*others, rule])
            self._editing_id = identifier
            self.set_error(tr("monitor_saving", self._language))
            self.preferences_changed.emit({"monitor_rules_json": document})
        except (ValueError, TypeError) as error:
            self.set_error(str(error))

    def set_error(self, text):
        self.error_label.setText(text)
        self.error_label.setVisible(bool(text))

    def _delete_rule(self):
        if not self._locked and self._editing_id:
            document = encode_rules([rule for rule in self._rules if rule.id != self._editing_id])
            self.preferences_changed.emit({"monitor_rules_json": document})

    def set_locked(self, locked):
        self._locked = locked
        for widget in (*self.fields.values(), self.rule_combo, self.new_button, self.save_button):
            widget.setEnabled(not locked)
        self.delete_button.setEnabled(not locked and bool(self._editing_id))

    def set_target(self, target):
        self._targets[target.role] = target
        self._render_status()

    def _render_status(self):
        rows, details = [], []
        for role, target in self._targets.items():
            report = target.observation_details
            details.append(role.label + " · " + tr(target.observation.value, self._language) + "\n" +
                           monitor_description(report, self._language))
            for row in report.get("rules", []) or [{"status": target.observation.value}]:
                rows.append([role.label + (" · " + row["name"] if row.get("name") else ""),
                             tr(row["status"], self._language), row.get("last_capture_utc", "") or "—",
                             row.get("last_source", "") or "—", str(row.get("matched_packets", 0))])
        self.table.setRowCount(len(rows))
        for index, values in enumerate(rows):
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(index, column, item)
        self.details.setPlainText("\n\n".join(details))
