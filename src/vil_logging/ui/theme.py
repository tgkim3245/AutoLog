"""Shared, font-independent desktop theme for the control panel and dialogs."""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QListView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionButton,
)

COLOR = {
    "ink": "#17253D",
    "navy": "#17253D",
    "blue": "#4263EB",
    "primary": "#4263EB",
    "mist": "#F2F5FA",
    "background": "#F2F5FA",
    "surface": "#FFFFFF",
    "border": "#DDE4EF",
    "muted": "#64748B",
    "subtle": "#7C8A9F",
    "ready": "#147D64",
    "ready_bg": "#EAF7F1",
    "attention": "#986314",
    "attention_bg": "#FFF5E2",
    "error": "#B63B4A",
    "error_bg": "#FFF0F1",
    "blue_bg": "#EDF1FF",
}

STYLE = """
QWidget {
    font-family: "Malgun Gothic", "Segoe UI", sans-serif;
    font-size: 12px; color: #17253D;
}
QMainWindow, QDialog { background: #F2F5FA; }
QLabel { background: transparent; border: none; }
QLabel[variant="eyebrow"] { color: #6B7C96; font-size: 10px; font-weight: 700; }
QLabel[variant="title"] { color: #17253D; font-size: 25px; font-weight: 700; }
QLabel[variant="section"] { color: #17253D; font-size: 12px; font-weight: 700; }
QLabel[variant="muted"] { color: #64748B; font-size: 12px; }
QLabel[variant="helper"] { color: #718198; font-size: 11px; }
QLabel[variant="status"] { border-radius: 7px; padding: 4px 7px; font-size: 11px; font-weight: 600; }
QLabel[tone="neutral"] { color: #64748B; background: #EDF1F6; }
QLabel[tone="ready"] { color: #147D64; background: #EAF7F1; }
QLabel[tone="checking"] { color: #4263EB; background: #EDF1FF; }
QLabel[tone="attention"] { color: #986314; background: #FFF5E2; }
QLabel[tone="error"] { color: #B63B4A; background: #FFF0F1; }
QFrame[panel="true"] { background: #FFFFFF; border: 1px solid #DDE4EF; border-radius: 12px; }
QFrame[role="card"] { background: #FFFFFF; border: 1px solid #DDE4EF; border-left: 3px solid #CCD6E6; border-radius: 9px; }
QFrame[role="card"][selected="true"] { border-color: #CDD6FF; border-left-color: #4263EB; background: #FCFDFF; }
QFrame[role="notice"] { background: #EDF1FF; border: 1px solid #D9E1FF; border-radius: 10px; }
QFrame[role="notice"][tone="ready"] { background: #EAF7F1; border-color: #D3EBE0; }
QFrame[role="notice"][tone="attention"] { background: #FFF5E2; border-color: #F1E3C5; }
QFrame[role="notice"][tone="error"] { background: #FFF0F1; border-color: #F3D9DD; }
QPushButton, QToolButton {
    background: #FFFFFF; border: 1px solid #DDE4EF; border-radius: 7px;
    padding: 7px 11px; min-height: 18px; color: #334763;
}
QPushButton:hover, QToolButton:hover { background: #EDF1FF; border-color: #B9C6FA; }
QPushButton:pressed, QToolButton:pressed { background: #DFE6FF; }
QPushButton:focus, QToolButton:focus { border: 2px solid #8B9FF7; padding: 6px 10px; }
QPushButton:disabled, QToolButton:disabled { color: #9DA9BB; background: #F7F9FC; border-color: #E4E9F1; }
QPushButton[variant="primary"] { background: #4263EB; color: #FFFFFF; border-color: #4263EB; font-weight: 700; }
QPushButton[variant="primary"]:hover { background: #3455D8; border-color: #3455D8; }
QPushButton[variant="danger"] { color: #B63B4A; background: #FFFFFF; border-color: #EDD1D7; }
QPushButton[variant="ghost"] { background: transparent; border-color: transparent; color: #62728B; }
QPushButton[variant="ghost"]:hover { background: #E7ECF6; color: #334763; }
QToolButton:checked { background: #17253D; color: #FFFFFF; border-color: #17253D; font-weight: 700; }
QToolButton[compact="true"] { min-height: 18px; padding: 4px 7px; font-size: 10px; }
QToolButton[compact="true"]:focus { padding: 3px 6px; }
QPushButton[compact="true"] { min-height: 16px; padding: 5px 8px; font-size: 11px; }
QLineEdit, QComboBox {
    border: 1px solid #D8E0EC; border-radius: 7px; background: #FFFFFF;
    padding: 8px 9px; color: #17253D; min-height: 18px;
    selection-background-color: #DCE4FF; selection-color: #17253D;
}
QLineEdit:focus, QComboBox:focus { border: 2px solid #849BF5; padding: 7px 8px; background: #FFFFFF; }
QLineEdit:disabled, QComboBox:disabled { background: #F6F8FB; color: #9BA7B9; border-color: #E2E8F1; }
QComboBox::drop-down { border: none; width: 25px; }
QComboBox::down-arrow { image: none; }
QComboBox QAbstractItemView {
    background: #FFFFFF; color: #17253D; border: 1px solid #CDD6E6;
    padding: 4px; outline: 0; selection-background-color: #EDF1FF;
    selection-color: #17253D;
}
QComboBox QAbstractItemView::item { padding: 6px 10px; border-radius: 5px; }
QComboBox QAbstractItemView::item:hover { background: #F2F5FA; }
QTabWidget::pane { border: 1px solid #DDE4EF; border-radius: 10px; background: #FFFFFF; top: -1px; }
QTabBar::tab { background: transparent; color: #718198; padding: 11px 16px; border-bottom: 3px solid transparent; }
QTabBar::tab:selected { color: #4263EB; border-bottom-color: #4263EB; font-weight: 700; }
QTabBar::tab:hover { color: #4263EB; background: #EDF1FF; }
QPlainTextEdit { border: 1px solid #DDE4EF; border-radius: 8px; background: #FFFFFF; padding: 8px; }
QCheckBox { spacing: 7px; background: transparent; }
QCheckBox::indicator { width: 15px; height: 15px; }
QCheckBox#developerLogCheckBox { font-size: 10px; color: #718198; spacing: 4px; }
QCheckBox#developerLogCheckBox::indicator { width: 12px; height: 12px; }
QListWidget, QTableWidget {
    border: 1px solid #DDE4EF; border-radius: 8px; background: #FFFFFF;
    font-size: 11px; alternate-background-color: #F8FAFD; outline: 0;
    selection-background-color: #EDF1FF; selection-color: #17253D;
}
QListWidget { padding: 5px; }
QListWidget::item { padding: 4px 3px; border-radius: 4px; }
QListWidget::item:selected { background: #EDF1FF; }
QHeaderView::section { background: #EAF0F8; color: #52647F; font-weight: 700; border: none; padding: 10px 6px; }
QTableWidget { gridline-color: #E9EEF6; }
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 7px; margin: 3px 0; }
QScrollBar::handle:vertical { background: #CDD6E6; border-radius: 3px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QGroupBox { background: #FFFFFF; border: 1px solid #DDE4EF; border-radius: 10px; margin-top: 15px; padding-top: 12px; font-weight: 700; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }
QToolTip { color: #FFFFFF; background: #17253D; border: none; padding: 7px; }
QMenu { background: #FFFFFF; border: 1px solid #DDE4EF; padding: 5px; }
QMenu::item { padding: 7px 20px; }
QMenu::item:selected { background: #EDF1FF; }
"""


def apply_theme(widget):
    widget.setStyleSheet(STYLE)


def refresh_style(widget):
    """Refresh a color/state property without replacing the widget's style sheet."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


class _ComboRowDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        natural = super().sizeHint(option, index)
        return QSize(natural.width(), max(36, natural.height()))


class ThemedComboBox(QComboBox):
    """Readable list rows and a font-independent disclosure arrow."""

    def __init__(self, parent=None):
        super().__init__(parent)
        view = QListView(self)
        view.setUniformItemSizes(True)
        view.setSpacing(2)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setView(view)
        self.setItemDelegate(_ComboRowDelegate(view))
        self.setMaxVisibleItems(8)

    def showPopup(self):
        view = self.view()
        rows = min(self.count(), self.maxVisibleItems())
        # Qt's menu-style combo popup can otherwise allocate only one row,
        # leaving a scroller over the second format option on Windows.
        view.setMinimumHeight(sum(max(36, view.sizeHintForRow(row)) + 2 * view.spacing()
                                  for row in range(rows)) + 10)
        super().showPopup()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#64748B" if self.isEnabled() else "#A7B2C2"), 1.5))
        center = QPointF(self.width() - 16, self.height() / 2)
        painter.drawLine(center + QPointF(-4, -2), center + QPointF(0, 2))
        painter.drawLine(center + QPointF(0, 2), center + QPointF(4, -2))
        painter.end()


class ThemedCheckBox(QCheckBox):
    """Keep Qt checkbox behavior while drawing a crisp, font-independent indicator."""

    def paintEvent(self, event):
        super().paintEvent(event)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        indicator = self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, self)
        box = QRectF(indicator).adjusted(0.75, 0.75, -0.75, -0.75)
        enabled = self.isEnabled()
        selected = self.isChecked()
        fill = COLOR["blue"] if selected else COLOR["surface"]
        stroke = COLOR["blue"] if selected else "#B7C5DA"
        if not enabled:
            fill = "#B6C2E2" if selected else "#F1F4F9"
            stroke = "#B6C2E2" if selected else "#D7DFEC"
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(stroke), 1.25))
        painter.setBrush(QColor(fill))
        painter.drawRoundedRect(box, 3, 3)
        if selected:
            tick = QPainterPath()
            tick.moveTo(QPointF(box.left() + box.width() * 0.22, box.top() + box.height() * 0.50))
            tick.lineTo(QPointF(box.left() + box.width() * 0.43, box.top() + box.height() * 0.72))
            tick.lineTo(QPointF(box.left() + box.width() * 0.79, box.top() + box.height() * 0.28))
            pen = QPen(QColor("#FFFFFF"), 1.7)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(tick)
        painter.end()
