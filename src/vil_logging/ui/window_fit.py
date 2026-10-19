"""Keep top-level windows inside the current screen's logical work area."""

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QScrollArea, QVBoxLayout, QWidget


def fit_window(window, available=None):
    screen = window.screen() or QApplication.primaryScreen()
    if available is None:
        if screen is None:
            return
        available = screen.availableGeometry()
    # Leave room for the native frame/title bar; Qt coordinates already account for DPI.
    width, height = max(1, available.width() - 16), max(1, available.height() - 48)
    layout = window.layout()
    if isinstance(window, QDialog) and layout is not None and not hasattr(window, "_fit_scroll") and (
            layout.minimumSize().height() > height):
        # Complex forms can exceed the screen even after the table shrinks.
        # Move the existing layout intact so the bottom actions remain reachable.
        content = QWidget()
        content.setLayout(layout)
        scroll = QScrollArea(window)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        outer = QVBoxLayout(window)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        window._fit_scroll = scroll
    window.setMinimumSize(min(window.minimumWidth(), width), min(window.minimumHeight(), height))
    window.setMaximumSize(width, height)
    window.resize(min(window.width(), width), min(window.height(), height))
    frame = window.frameGeometry()
    window.move(max(available.left(), min(frame.left(), available.right() - frame.width() + 1)),
                max(available.top(), min(frame.top(), available.bottom() - frame.height() + 1)))


class ScreenFit(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self._handle = None
        window.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in {QEvent.Type.Show, QEvent.Type.ScreenChangeInternal}:
            handle = self.window.windowHandle()
            if handle is not None and self._handle is None:
                self._handle = handle
                handle.screenChanged.connect(lambda _screen: fit_window(self.window))
            QTimer.singleShot(0, lambda: fit_window(self.window))
        return False
