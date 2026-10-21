"""Main capture action with a lightweight, visibility-aware progress indicator."""

from math import cos, pi, sin

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QPushButton

from .theme import refresh_style


class CaptureButton(QPushButton):
    def __init__(self):
        super().__init__()
        self.setObjectName("loggingButton")
        self.setFixedHeight(52)
        self.setIconSize(QSize(20, 20))
        self._busy = False
        self._frame = 0
        self._timer = QTimer(self)
        self._timer.setInterval(90)
        self._timer.timeout.connect(self._animate)

    def set_status(self, text, tone, enabled, busy, tooltip):
        self.setText(text)
        self.setAccessibleName(text)
        self.setToolTip(tooltip)
        self.setAccessibleDescription(tooltip)
        self.setEnabled(enabled)
        self.setCursor(Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor)
        if self.property("tone") != tone:
            self.setProperty("tone", tone)
            refresh_style(self)
        self._busy = busy
        if busy:
            self._animate()
            if self.isVisible():
                self._timer.start()
        else:
            self._timer.stop()
            self.setIcon(QIcon())

    def _animate(self):
        self._frame = (self._frame + 1) % 12
        canvas = QPixmap(40, 40)
        canvas.setDevicePixelRatio(2)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for index in range(12):
            color = QColor("#FFFFFF")
            color.setAlpha(55 + ((index - self._frame) % 12) * 18)
            painter.setPen(QPen(color, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            angle = index * pi / 6
            painter.drawLine(round(10 + 5 * cos(angle)), round(10 + 5 * sin(angle)),
                             round(10 + 8 * cos(angle)), round(10 + 8 * sin(angle)))
        painter.end()
        icon = QIcon(canvas)
        icon.addPixmap(canvas, QIcon.Mode.Disabled)
        self.setIcon(icon)

    def showEvent(self, event):
        super().showEvent(event)
        if self._busy:
            self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self.width() < 360
        if self.property("compact") != compact:
            self.setProperty("compact", compact)
            refresh_style(self)
