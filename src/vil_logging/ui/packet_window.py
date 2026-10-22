"""Bounded packet display; capture and monitoring never depend on this view."""

import logging
from collections import deque

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableView,
    QVBoxLayout,
)

from vil_logging.contracts.models import PacketSummary

from .i18n import tr
from .theme import ThemedCheckBox, apply_theme

logger = logging.getLogger(__name__)


class PacketTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows, self.headers = [], []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 5

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return self.rows[index.row()][index.column()]
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.headers[section] if section < len(self.headers) else ""
        return None

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()


class PacketWindow(QDialog):
    MAX_PACKETS = 1000

    def __init__(self, parent=None):
        super().__init__(parent)
        apply_theme(self)
        self.setModal(False)
        self.resize(940, 500)
        self.packets: deque[PacketSummary] = deque(maxlen=self.MAX_PACKETS)
        self._dirty = False
        self._language = "ko"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)
        eyebrow = QLabel("AUTOLOG / PACKET INSPECTOR")
        eyebrow.setProperty("variant", "eyebrow")
        layout.addWidget(eyebrow)
        heading = QHBoxLayout()
        self.title = QLabel()
        self.title.setProperty("variant", "title")
        heading.addWidget(self.title, 1)
        self.count_label = QLabel()
        self.count_label.setProperty("variant", "helper")
        heading.addWidget(self.count_label)
        layout.addLayout(heading)
        controls = QHBoxLayout()
        self.filter_label = QLabel()
        self.filter_label.setProperty("variant", "section")
        self.filter_input = QLineEdit()
        self.filter_input.setObjectName("packetFilterInput")
        self.pause_check = ThemedCheckBox()
        self.pause_check.setObjectName("packetPauseCheckBox")
        controls.addWidget(self.filter_label)
        controls.addWidget(self.filter_input, 1)
        controls.addWidget(self.pause_check)
        layout.addLayout(controls)
        self.hint = QLabel()
        self.hint.setProperty("variant", "helper")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.table = QTableView()
        self.model = PacketTableModel(self.table)
        self.table.setModel(self.model)
        self.table.setObjectName("packetTable")
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for column, width in ((0, 170), (3, 90), (4, 75)):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(column, width)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(34)
        layout.addWidget(self.table, 1)
        self.filter_input.textChanged.connect(self._mark_dirty)
        self.pause_check.toggled.connect(self._mark_dirty)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.set_language("ko")

    def _mark_dirty(self, *_):
        logger.debug("Packet display controls: paused=%s filter=%r", self.pause_check.isChecked(), self.filter_input.text())
        self._dirty = True

    def add_packet(self, packet: PacketSummary):
        self.packets.append(packet)
        self._dirty = True

    def clear_session(self):
        self.packets.clear()
        self.model.set_rows([])
        self.count_label.setText(tr("packet_counts", self._language).format(count=0))
        self._dirty = True

    def set_language(self, language: str):
        self._language = language
        self.setWindowTitle(tr("packets", language))
        self.title.setText(tr("packets", language))
        self.filter_label.setText(tr("filter", language))
        self.pause_check.setText(tr("pause", language))
        self.hint.setText(tr("packet_hint", language))
        self.filter_input.setPlaceholderText(tr("packet_filter_placeholder", language))
        self.count_label.setText(tr("packet_counts", language).format(count=len(self.packets)))
        self.model.headers = [tr(key, language) for key in ("time", "source", "destination", "protocol", "length")]
        self.model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, 4)

    def refresh(self):
        if not self._dirty or self.pause_check.isChecked() or not self.isVisible():
            return
        query = self.filter_input.text().strip().casefold()
        rows = []
        for packet in self.packets:
            row = (
                packet.timestamp,
                " / ".join(dict.fromkeys(part for part in (packet.source, packet.source_mac) if part)),
                " / ".join(dict.fromkeys(part for part in (packet.destination, packet.destination_mac) if part)),
                packet.protocol,
                str(packet.length),
            )
            if not query or query in " ".join(row).casefold():
                rows.append(row)
        self.count_label.setText(tr("packet_counts", self._language).format(count=len(self.packets)))
        self.model.set_rows(rows)
        self.table.scrollToBottom()
        self._dirty = False

    def showEvent(self, event):
        super().showEvent(event)
        self._dirty = True
        QTimer.singleShot(0, self.refresh)
