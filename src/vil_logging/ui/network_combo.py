"""Network picker with bounded live receive sparklines and no capture subprocesses."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from vil_logging.diagnostics.connections import _nic_key
from vil_logging.diagnostics.network_activity import ActivityHistory, read_receive_counters

from .theme import ThemedComboBox

log = logging.getLogger(__name__)
ACTIVITY_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class NetworkDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(560, 44 if index.data(Qt.ItemDataRole.UserRole) else 36)

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        painter.save()
        rect = option.rect.adjusted(10, 0, -10, 0)
        has_nic = bool(index.data(Qt.ItemDataRole.UserRole))
        text_rect = rect.adjusted(0, 0, -176 if has_nic else 0, 0)
        painter.setPen(QColor("#17253D"))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         option.fontMetrics.elidedText(text, Qt.TextElideMode.ElideRight, text_rect.width()))
        if has_nic:
            activity = index.data(ACTIVITY_ROLE) or {}
            history, rate = activity.get("history", []), activity.get("pps")
            graph = QRectF(rect.right() - 163, rect.top() + 8, 102, rect.height() - 16)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor("#DDE4EF"), 1))
            painter.drawLine(graph.bottomLeft(), graph.bottomRight())
            peak = max((value for value in history if value is not None), default=0)
            path, started = QPainterPath(), False
            for i, value in enumerate(history):
                if value is None:
                    started = False
                    continue
                point = QPointF(graph.left() + graph.width() * i / max(23, len(history) - 1),
                                graph.bottom() - graph.height() * value / max(1, peak))
                if started:
                    path.lineTo(point)
                else:
                    path.moveTo(point)
                    started = True
            painter.setPen(QPen(QColor("#4263EB"), 1.6))
            painter.drawPath(path)
            painter.setPen(QColor("#64748B"))
            caption = "—" if rate is None else f"{rate / 1000:.1f}k pps" if rate >= 1000 else f"{rate:.0f} pps"
            painter.drawText(rect.adjusted(rect.width() - 58, 0, 0, 0),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, caption)
        painter.restore()


class NetworkComboBox(ThemedComboBox):
    popup_opened = Signal()
    popup_closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view().setUniformItemSizes(False)
        self.setItemDelegate(NetworkDelegate(self.view()))
        self.setMaxVisibleItems(10)
        self.popup_open = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="One Click Log-NIC")
        self._future = None
        self._history = ActivityHistory()
        self._activity = {}
        self._error_reported = False
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self.destroyed.connect(lambda: self._executor.shutdown(wait=False, cancel_futures=True))

    def set_sampling(self, enabled):
        if enabled and not self._timer.isActive():
            log.debug("network.activity_started", extra={"selected_nic": self.currentData()})
            self._history.reset_baseline()
            self._timer.start()
            self._tick()
        elif not enabled:
            if self._timer.isActive():
                log.debug("network.activity_stopped")
            self._timer.stop()

    def _tick(self):
        if self._future is not None and self._future.done():
            try:
                when, counters = self._future.result()
                self._error_reported = False
            except Exception:
                if not self._error_reported:
                    log.warning("network.activity_unavailable", exc_info=True)
                    self._error_reported = True
                when, counters = time.monotonic(), {}
            self._activity = self._history.update(when, counters)
            self.refresh_activity()
            self._future = None
        if self._future is None:
            self._future = self._executor.submit(read_receive_counters)

    def refresh_activity(self):
        for index in range(self.count()):
            identifier = self.itemData(index)
            if identifier:
                self.setItemData(index, self._activity.get(_nic_key(identifier), {}), ACTIVITY_ROLE)
        self.view().viewport().update()

    def showPopup(self):
        self.popup_open = True
        self.popup_opened.emit()
        super().showPopup()

    def hidePopup(self):
        super().hidePopup()
        self.popup_open = False
        self.popup_closed.emit()
