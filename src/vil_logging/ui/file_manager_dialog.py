"""Read-only file operation history and explicit previous-file deletion confirmation."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from .i18n import tr
from .theme import apply_theme
from .window_fit import ScreenFit


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


class FileHistoryDialog(QDialog):
    refresh_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("fileHistoryDialog")
        self.resize(820, 460)
        self._screen_fit = ScreenFit(self)
        apply_theme(self)
        self._language = "ko"
        self._operations = []
        self._last_result = None
        layout = QVBoxLayout(self)
        self.text = QPlainTextEdit()
        self.text.setObjectName("fileOperationHistory")
        self.text.setReadOnly(True)
        layout.addWidget(self.text, 1)
        self.result_details = QPlainTextEdit()
        self.result_details.setReadOnly(True)
        self.result_details.setMaximumHeight(90)
        self.result_details.hide()
        layout.addWidget(self.result_details)
        row = QHBoxLayout()
        self.refresh_button = QPushButton()
        self.refresh_button.clicked.connect(self.refresh_requested)
        row.addWidget(self.refresh_button)
        row.addStretch()
        self.close_button = QPushButton()
        self.close_button.clicked.connect(self.close)
        row.addWidget(self.close_button)
        layout.addLayout(row)
        self.set_language("ko")

    def set_language(self, language):
        self._language = language
        self.setWindowTitle(tr("file_operations", language))
        self.refresh_button.setText(tr("refresh", language))
        self.close_button.setText(tr("close", language))
        self.set_operations(self._operations)
        if self._last_result:
            self.set_result(self._last_result)

    def set_operations(self, operations):
        self._operations = operations
        lines = []
        for operation in operations:
            kind = tr("file_kind_" + operation["kind"], self._language)
            state = tr("file_item_pending" if operation["status"] == "pending" else
                       "file_result_" + operation["status"], self._language)
            lines.append(f'{operation["created_utc"]}  {kind}  {state}')
            for item in operation["document"]["items"]:
                state = tr("file_item_" + item["status"], self._language)
                lines.append(f'  {state}: {item["source"]}')
                if item.get("destination"):
                    lines.append("  → " + item["destination"])
                if item.get("error"):
                    lines.append("  " + item["error"])
            lines.append("")
        self.text.setPlainText("\n".join(lines) or tr("events_empty", self._language))

    def set_result(self, result):
        self._last_result = result
        lines = [tr("file_kind_" + result["kind"], self._language) + " · " +
                 tr("file_result_" + result["status"], self._language), result.get("error", "")]
        for item in result.get("items", []):
            lines.append(f'{item.get("actual_path", item["source"])}\n{item.get("error", "")}')
        self.result_details.setPlainText("\n".join(line for line in lines if line))
        self.result_details.show()
