"""Zipy receive validation rules embedded in Settings."""
from dataclasses import asdict
from uuid import uuid4

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from vil_logging.monitors.rules import (
    DEFAULT_RULE_ID,
    MAX_RULES,
    DefaultRuleCapacityError,
    EthernetRule,
    encode_rules,
    parse_rules,
    restore_default_rule,
)

from .i18n import tr
from .theme import ThemedComboBox

FIELDS = ("name", "popup_message", "source_mac_prefix", "minimum_pps", "protocol", "destination_ip",
          "destination_mac", "expected_ip", "expected_mac", "timeout_ms", "grace_ms", "max_delay_ms", "recovery_count")

def _field_text(field):
    return field.toPlainText() if isinstance(field, QPlainTextEdit) else field.text()

def _set_field_text(field, text):
    field.setPlainText(text) if isinstance(field, QPlainTextEdit) else field.setText(text)

def monitor_description(report, language):
    lines = []
    for reason in report.get("reasons", []):
        lines.append(tr("monitor_reason_" + reason, language))
    for row in report.get("rules", []):
        lines.append(row["name"] + " · " + tr(row["status"], language))
        lines.extend(tr("monitor_reason_" + reason, language) for reason in row["reasons"])
        lines.extend(row.get("violation_utc", "") + " · " + tr("monitor_reason_" + reason, language)
                     for reason in row.get("violation_reasons", []) if reason not in row["reasons"])
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

class ValidationPanel(QWidget):
    preferences_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("zipyValidationPanel")
        self._language = "ko"
        self._rules = []
        self._editing_id = ""
        self._locked = self._updating = False
        self._drafts = {}
        self._document = None
        self._restore_document = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        self.rules_hint = QLabel()
        self.rules_hint.setWordWrap(True)
        layout.addWidget(self.rules_hint)
        row = QHBoxLayout()
        self.rule_combo = ThemedComboBox()
        self.rule_combo.currentIndexChanged.connect(self._choose_rule)
        row.addWidget(self.rule_combo, 1)
        self.new_button = QPushButton()
        self.new_button.clicked.connect(self._new_rule)
        row.addWidget(self.new_button)
        self.delete_button = QPushButton()
        self.delete_button.clicked.connect(self._delete_rule)
        row.addWidget(self.delete_button)
        layout.addLayout(row)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        form = QFormLayout(body)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.fields, self.labels = {}, {}
        for key in FIELDS:
            field = QPlainTextEdit() if key == "popup_message" else QLineEdit()
            if key == "popup_message":
                field.setFixedHeight(88)
            field.setObjectName("validation_" + key)
            self.fields[key], self.labels[key] = field, QLabel()
            form.addRow(self.labels[key], field)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setProperty("tone", "error")
        self.error_label.hide()
        layout.addWidget(self.error_label)
        self.save_button = QPushButton()
        self.save_button.setProperty("variant", "primary")
        self.save_button.clicked.connect(self._save_rule)
        actions = QHBoxLayout()
        self.restore_button = QPushButton()
        self.restore_button.setObjectName("zipyRestoreDefaultButton")
        self.restore_button.clicked.connect(self._restore_default)
        actions.addWidget(self.restore_button)
        actions.addWidget(self.save_button, 1)
        layout.addLayout(actions)
        self.set_language("ko")
        self._render_rules()

    def set_language(self, language):
        self._language = language
        self.rules_hint.setText(tr("validation_help", language))
        if self.rule_combo.count():
            self.rule_combo.setItemText(0, tr("monitor_new", language))
        for key, label in self.labels.items():
            label.setText(tr("monitor_field_" + key, language))
            self.fields[key].setPlaceholderText(tr("monitor_optional" if key in {
                "popup_message", "source_mac_prefix", "minimum_pps", "protocol", "destination_ip",
                "destination_mac", "expected_ip", "expected_mac"} else "monitor_required", language))
        for button, key in ((self.new_button, "monitor_new"), (self.delete_button, "monitor_delete"),
                            (self.save_button, "monitor_save"), (self.restore_button, "monitor_restore_default")):
            button.setText(tr(key, language))
        self.restore_button.setToolTip(tr("monitor_restore_default_help", language))

    def set_settings(self, settings):
        if settings.monitor_rules_json == self._document:
            return
        first_load = self._document is None
        self._document = settings.monitor_rules_json
        if self._document == self._restore_document:
            self._editing_id = DEFAULT_RULE_ID
            self._restore_document = None
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
            self._drafts[self._editing_id] = {key: _field_text(field) for key, field in self.fields.items()}
            self._load_rule()

    def _load_rule(self):
        self._editing_id = self.rule_combo.currentData() or ""
        rule = next((rule for rule in self._rules if rule.id == self._editing_id), None)
        values = self._drafts.get(self._editing_id, asdict(rule) if rule else {})
        for key, field in self.fields.items():
            _set_field_text(field, str(values.get(key, "")))
        self.delete_button.setEnabled(not self._locked and self._restore_document is None and bool(rule))

    def _new_rule(self):
        self.rule_combo.setCurrentIndex(0)

    def _save_rule(self):
        if self._locked or self._restore_document is not None:
            return
        try:
            values = {key: _field_text(field).strip() for key, field in self.fields.items()}
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
        if self._restore_document is not None:
            self._restore_document = None
            self.set_locked(self._locked)
        self.error_label.setText(text)
        self.error_label.setVisible(bool(text))

    def _delete_rule(self):
        if not self._locked and self._restore_document is None and self._editing_id:
            document = encode_rules([rule for rule in self._rules if rule.id != self._editing_id])
            self.preferences_changed.emit({"monitor_rules_json": document})

    def _restore_default(self):
        if self._locked or self._restore_document is not None:
            return
        try:
            document = restore_default_rule(self._document or "")
            if document == self._document:
                self._drafts.pop(DEFAULT_RULE_ID, None)
                self._editing_id = DEFAULT_RULE_ID
                self._render_rules()
                self.set_error("")
                return
            self.set_error(tr("monitor_saving", self._language))
            self._restore_document = document
            self.set_locked(self._locked)
            self.preferences_changed.emit({"monitor_rules_json": document})
        except DefaultRuleCapacityError:
            self.set_error(tr("monitor_restore_default_limit", self._language))
        except (ValueError, TypeError) as error:
            self.set_error(str(error))

    def set_locked(self, locked):
        self._locked = locked
        for widget in (*self.fields.values(), self.rule_combo, self.new_button, self.save_button, self.restore_button):
            widget.setEnabled(not locked and self._restore_document is None)
        self.delete_button.setEnabled(not locked and self._restore_document is None and bool(self._editing_id))
