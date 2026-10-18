"""Review registered recovery candidates and explicitly confirm external recording stopped."""

from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .i18n import tr
from .theme import ThemedCheckBox, apply_theme


class RecoveryDialog(QDialog):
    requested = Signal(object)
    refresh_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("recoveryDialog")
        self.resize(980, 660)
        self.setMinimumSize(780, 580)
        apply_theme(self)
        self._language = "ko"
        self._report = {}
        self._rows = []
        self._locked = False
        layout = QVBoxLayout(self)
        self.help_label = QLabel()
        self.help_label.setWordWrap(True)
        layout.addWidget(self.help_label)
        self.table = QTableWidget(0, 4)
        self.table.setObjectName("recoveryTable")
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.verticalHeader().hide()
        for column in (0, 1, 2):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table, 1)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(155)
        self.details.setMaximumHeight(220)
        layout.addWidget(self.details)
        self.stopped_check = ThemedCheckBox()
        self.stopped_check.setObjectName("recoveryStoppedCheck")
        self.stopped_check.toggled.connect(self._update_buttons)
        layout.addWidget(self.stopped_check)
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)
        controls = QHBoxLayout()
        self.refresh_button = QPushButton()
        self.refresh_button.clicked.connect(lambda: self.requested.emit({"action": "recheck"}))
        self.folder_button = QPushButton()
        self.folder_button.clicked.connect(self._open_folder)
        self.retry_button = QPushButton()
        self.retry_button.clicked.connect(lambda: self.requested.emit({"action": "retry_stop"}))
        for button in (self.refresh_button, self.folder_button, self.retry_button):
            controls.addWidget(button)
        controls.addStretch()
        layout.addLayout(controls)
        actions = QHBoxLayout()
        self.publish_button = QPushButton()
        self.publish_button.setObjectName("recoveryPublishButton")
        self.publish_button.clicked.connect(lambda: self._request("publish"))
        self.finish_button = QPushButton()
        self.finish_button.setObjectName("recoveryFinishButton")
        self.finish_button.clicked.connect(lambda: self._request("finish"))
        self.ack_button = QPushButton()
        self.ack_button.clicked.connect(lambda: self._request("acknowledge"))
        self.close_button = QPushButton()
        self.close_button.clicked.connect(self.close)
        for button in (self.publish_button, self.finish_button, self.ack_button, self.close_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.set_language("ko")

    def set_language(self, language):
        self._language = language
        self.setWindowTitle(tr("recovery", language))
        self.help_label.setText(tr("recovery_help", language))
        self.stopped_check.setText(tr("recovery_stopped", language))
        for button, key in ((self.refresh_button, "recovery_recheck"), (self.folder_button, "open_folder"),
                            (self.retry_button, "recovery_retry_stop"), (self.publish_button, "recovery_publish"),
                            (self.finish_button, "recovery_finish"), (self.ack_button, "recovery_acknowledge"),
                            (self.close_button, "close")):
            button.setText(tr(key, language))
        self.table.setHorizontalHeaderLabels([tr(key, language) for key in (
            "capture_number", "filename", "file_state", "full_path")])
        self.set_report(self._report)

    def set_report(self, report):
        selected = self._selected()
        old_key = self._row_key(selected) if selected else None
        if report != self._report:
            self.stopped_check.setChecked(False)
        self._report = report
        self._rows = []
        for session in report.get("sessions", []):
            for file in session["files"]:
                self._rows.append({"kind": "capture", "session": session, "file": file})
        for operation in report.get("operations", []):
            self._rows.append({"kind": "operation", "operation": operation})
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._rows))
        for row, entry in enumerate(self._rows):
            if entry["kind"] == "capture":
                session, file = entry["session"], entry["file"]
                role = {"can": "CAN", "diag": "Diag", "ethernet": "Zipy"}[file["role"]]
                values = [f'{session["index"]} · {role}', file["filename"],
                          tr("file_state_" + file["state"], self._language), file["temp_path"]]
            else:
                operation = entry["operation"]
                values = [tr("file_kind_" + operation["kind"], self._language),
                          operation["operation_id"][:8], tr("file_state_review", self._language),
                          operation["document"]["items"][0]["source"]]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(row, column, item)
        if self._rows:
            chosen = next((i for i, row in enumerate(self._rows) if self._row_key(row) == old_key), 0)
            self.table.selectRow(chosen)
        self.table.blockSignals(False)
        self._selection_changed()

    @staticmethod
    def _row_key(row):
        return ((row["session"]["session_id"], row["file"]["role"]) if row["kind"] == "capture"
                else row["operation"]["operation_id"])

    def _selected(self):
        index = self.table.currentRow()
        return self._rows[index] if 0 <= index < len(self._rows) else None

    def _selection_changed(self):
        row = self._selected()
        lines = []
        if row:
            candidates = (row["file"]["candidates"] if row["kind"] == "capture" else row["operation"]["evidence"])
            if row["kind"] == "capture":
                lines.append(tr("recovery_destination", self._language) + ": " + row["file"]["final_path"])
                lines.append(tr("recovery_finish_help", self._language))
            else:
                lines.append(tr("recovery_ack_help", self._language))
            for candidate in candidates:
                status = (candidate["error"] if candidate.get("error") else
                          tr("recovery_present" if candidate.get("present") else "file_state_missing", self._language))
                size = candidate.get("identity", {}).get("bytes")
                lines.append(f'{status}{" · " + str(size) + " bytes" if size is not None else ""}\n{candidate["path"]}')
            if row["kind"] == "capture":
                error = row["file"]["metadata"].get("error", "")
                if error:
                    lines.append(error)
            else:
                for item in row["operation"]["document"]["items"]:
                    if item.get("error"):
                        lines.append(item["error"])
        self.details.setPlainText("\n\n".join(lines) if lines else tr("recovery_empty", self._language))
        self._update_buttons()

    def set_locked(self, locked):
        self._locked = locked
        self._update_buttons()

    def _update_buttons(self, *_):
        row = self._selected()
        live = bool(self._report.get("live_session_id"))
        ready = bool(row) and not self._locked and not live and self.stopped_check.isChecked()
        capture = bool(row) and row["kind"] == "capture"
        self.publish_button.setEnabled(ready and capture and not row["session"]["demo"] and
            row["file"]["state"] not in {"published", "deleted", "not_created", "retained", "unconfirmed"})
        self.finish_button.setEnabled(ready and capture)
        self.ack_button.setEnabled(ready and not capture)
        self.refresh_button.setEnabled(not self._locked and not live)
        self.retry_button.setEnabled(not self._locked and live)
        self.folder_button.setEnabled(bool(row))
        self.stopped_check.setEnabled(not self._locked and not live)

    def _request(self, action):
        row = self._selected()
        if not row or self._locked or not self.stopped_check.isChecked() or self._report.get("live_session_id"):
            return
        if row["kind"] == "capture":
            request = {"session_id": row["session"]["session_id"], "role": row["file"]["role"],
                       "token": row["session"]["token"]}
        else:
            request = {"operation_id": row["operation"]["operation_id"], "token": row["operation"]["token"]}
        self.requested.emit({**request, "action": action, "stopped": True})

    def _open_folder(self):
        row = self._selected()
        if row:
            path = (row["file"]["temp_path"] if row["kind"] == "capture"
                    else row["operation"]["document"]["items"][0]["source"])
            folder = Path(path).parent
            while not folder.exists() and folder != folder.parent:
                folder = folder.parent
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def set_result(self, result):
        key = "recovery_done" if result.get("success") else "recovery_error"
        self.result_label.setText(tr(key, self._language) +
                                 ("\n" + result["error"] if result.get("error") else ""))
