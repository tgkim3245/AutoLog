"""Completed capture list and explicit full-path deletion confirmation."""

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
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
from .theme import apply_theme


class DeleteFilesDialog(QDialog):
    def __init__(self, files: list[dict], language: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("delete_confirm_title", language))
        self.resize(730, 380)
        apply_theme(self)
        layout = QVBoxLayout(self)
        label = QLabel(tr("delete_confirm_help", language).format(count=len(files)))
        label.setWordWrap(True)
        layout.addWidget(label)
        self.paths = QPlainTextEdit("\n\n".join(file["path"] for file in files))
        self.paths.setReadOnly(True)
        layout.addWidget(self.paths, 1)
        buttons = QDialogButtonBox()
        self.cancel_button = buttons.addButton(tr("cancel", language), QDialogButtonBox.ButtonRole.RejectRole)
        self.confirm_button = buttons.addButton(tr("delete_permanently", language), QDialogButtonBox.ButtonRole.AcceptRole)
        self.confirm_button.setProperty("variant", "danger")
        self.confirm_button.setAutoDefault(False)
        self.cancel_button.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def confirm_delete(files: list[dict], language: str, parent) -> bool:
    return bool(files) and DeleteFilesDialog(files, language, parent).exec() == QDialog.DialogCode.Accepted


class FileManagerDialog(QDialog):
    delete_requested = Signal(object)
    refresh_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("fileManagerDialog")
        self.resize(940, 510)
        self.setMinimumSize(720, 400)
        apply_theme(self)
        self._language = "ko"
        self._history = []
        self._files = []
        self._locked = False
        self._operations = []
        self._last_result = None
        layout = QVBoxLayout(self)
        self.help_label = QLabel()
        self.help_label.setWordWrap(True)
        layout.addWidget(self.help_label)
        self.table = QTableWidget(0, 4)
        self.table.setObjectName("captureFileTable")
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._update_buttons)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self.table, 1)
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)
        self.result_details = QPlainTextEdit()
        self.result_details.setReadOnly(True)
        self.result_details.setMaximumHeight(90)
        self.result_details.hide()
        layout.addWidget(self.result_details)
        controls = QHBoxLayout()
        self.refresh_button = QPushButton()
        self.refresh_button.clicked.connect(self.refresh_requested)
        controls.addWidget(self.refresh_button)
        self.folder_button = QPushButton()
        self.folder_button.clicked.connect(self._open_folder)
        controls.addWidget(self.folder_button)
        self.history_button = QPushButton()
        self.history_button.clicked.connect(self._show_operations)
        controls.addWidget(self.history_button)
        controls.addStretch()
        self.delete_button = QPushButton()
        self.delete_button.setObjectName("deleteSelectedFilesButton")
        self.delete_button.clicked.connect(self._delete)
        controls.addWidget(self.delete_button)
        self.close_button = QPushButton()
        self.close_button.clicked.connect(self.close)
        controls.addWidget(self.close_button)
        layout.addLayout(controls)
        self.set_language("ko")

    def set_language(self, language):
        self._language = language
        self.setWindowTitle(tr("file_manager", language))
        self.help_label.setText(tr("file_manager_help", language))
        self.refresh_button.setText(tr("refresh", language))
        self.folder_button.setText(tr("open_folder", language))
        self.history_button.setText(tr("file_operations", language))
        self.delete_button.setText(tr("delete_selected", language))
        self.close_button.setText(tr("close", language))
        self.table.setHorizontalHeaderLabels([tr(key, language) for key in ("capture_number", "filename", "file_state", "full_path")])
        self.set_history(self._history)
        if self._last_result:
            self.set_result(self._last_result)

    def set_history(self, history: list[dict]):
        def selection_key(file):
            return (file["session_id"], file["role"], file["path"], tuple(sorted(file["identity"].items())))
        checked = {selection_key(file) for file in self.selected_files()}
        self._history = history
        self._files = [dict(file, index=str(session["index"]), created_utc=session["created_utc"])
                       for session in history for file in session["files"]]
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._files))
        for row, file in enumerate(self._files):
            label = {"can": "CAN", "diag": "Diag", "ethernet": "Zipy"}.get(file["role"], file["role"])
            values = [f'{file["index"]} · {label}', Path(file["path"]).name,
                      tr("file_state_" + file["status"], self._language), file["path"]]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(file["path"] + "\n" + file["created_utc"] + "\n" + file["error"])
                if column == 0 and file["manageable"]:
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Checked if selection_key(file) in checked else Qt.CheckState.Unchecked)
                self.table.setItem(row, column, item)
        self.table.blockSignals(False)
        self._update_buttons()

    def set_locked(self, locked: bool):
        self._locked = locked
        self.table.setEnabled(not locked)
        self._update_buttons()

    def selected_files(self):
        return [file for row, file in enumerate(self._files)
                if file["manageable"] and self.table.item(row, 0).checkState() == Qt.CheckState.Checked]

    def _update_buttons(self, *_):
        self.delete_button.setEnabled(not self._locked and bool(self.selected_files()))
        self.folder_button.setEnabled(self.table.currentRow() >= 0)

    def _delete(self):
        selected = self.selected_files()
        if not self._locked and confirm_delete(selected, self._language, self):
            self.delete_requested.emit(selected)

    def _open_folder(self):
        row = self.table.currentRow()
        if row >= 0:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self._files[row]["path"]).parent)))

    def set_result(self, result: dict):
        self._last_result = result
        self.result_label.setText(tr("file_kind_" + result["kind"], self._language) + " · " +
                                  tr("file_result_" + result["status"], self._language))
        lines = [result.get("error", "")]
        for item in result.get("items", []):
            state = tr("file_item_" + item["status"], self._language)
            lines.append(f'{state}: {item.get("actual_path", item["source"])}\n{item.get("error", "")}')
        self.result_details.setPlainText("\n".join(line for line in lines if line))
        self.result_details.show()

    def set_operations(self, operations: list[dict]):
        self._operations = operations

    def _show_operations(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("file_operations", self._language))
        dialog.resize(820, 460)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        lines = []
        for operation in self._operations:
            kind = tr("file_kind_" + operation["kind"], self._language)
            state = tr("file_result_" + operation["status"], self._language)
            if operation["status"] == "pending":
                state = tr("file_item_pending", self._language)
            lines.append(f'{operation["created_utc"]}  {kind}  {state}')
            for item in operation["document"]["items"]:
                state = tr("file_item_" + item["status"], self._language)
                lines.append(f'  {state}: {item["source"]}')
                if item.get("destination"):
                    lines.append("  → " + item["destination"])
                if item.get("error"):
                    lines.append("  " + item["error"])
            lines.append("")
        text.setPlainText("\n".join(lines) or tr("events_empty", self._language))
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()
