"""One keyboard-accessible button cycles the three persisted display languages."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QStyle, QStyleOptionToolButton, QToolButton


class LanguageButton(QToolButton):
    language_requested = Signal(str)
    LANGUAGES = ("ko", "en", "zh")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.language = "ko"
        self.setObjectName("languageToggleButton")
        self.setText("한 | EN | 中")
        self.setMinimumWidth(94)
        self.setProperty("compact", True)
        self.clicked.connect(self._cycle)
        self.set_language("ko")

    def _cycle(self):
        self.language_requested.emit(self.LANGUAGES[(self.LANGUAGES.index(self.language) + 1) % 3])

    def set_language(self, language):
        self.language = language
        current = {"ko": "한국어", "en": "English", "zh": "中文"}[language]
        self.setToolTip({"ko": "클릭하여 언어 변경: 한 → EN → 中", "en": "Click to change language: 한 → EN → 中",
                         "zh": "点击切换语言：한 → EN → 中"}[language])
        self.setAccessibleName(f"{current} · 한 / EN / 中")
        self.update()

    def paintEvent(self, event):
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        option.text = ""
        painter = QPainter(self)
        self.style().drawComplexControl(QStyle.ComplexControl.CC_ToolButton, option, painter, self)
        rect = self.rect().adjusted(5, 2, -5, -2)
        width = rect.width() / 3
        for index, (language, label) in enumerate(zip(self.LANGUAGES, ("한", "EN", "中"), strict=True)):
            part = rect.adjusted(round(width * index), 0, -round(width * (2 - index)), 0)
            font = self.font()
            font.setBold(language == self.language)
            painter.setFont(font)
            painter.setPen(QColor("#4263EB" if language == self.language else "#64748B"))
            painter.drawText(part, Qt.AlignmentFlag.AlignCenter, label)
            if index < 2:
                painter.setPen(QColor("#D4DDEC"))
                painter.drawLine(part.right(), rect.center().y() - 5, part.right(), rect.center().y() + 5)
