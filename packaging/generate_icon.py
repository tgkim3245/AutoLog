"""Render the repository SVG into a multi-resolution Windows icon."""

import os
import struct
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QFontDatabase, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


def main():
    app = QGuiApplication.instance() or QGuiApplication([])
    for name in ("ariblk.ttf", "arialbd.ttf", "segoeuib.ttf"):
        font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
        if font.is_file():
            QFontDatabase.addApplicationFont(str(font))
    root = Path(__file__).resolve().parents[1]
    renderer = QSvgRenderer(str(root / "assets/one_click_log.svg"))
    if not renderer.isValid():
        raise ValueError("Invalid application SVG")
    frames = []
    for size in (16, 24, 32, 48, 64, 128, 256):
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise ValueError("Could not encode icon frame")
        frames.append((size, bytes(data)))
    offset = 6 + 16 * len(frames)
    entries = []
    for size, data in frames:
        entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    target = root / "assets/one_click_log.ico"
    target.write_bytes(struct.pack("<HHH", 0, 1, len(frames)) + b"".join(entries) + b"".join(data for _, data in frames))
    print(f"Generated {target.name}: {len(frames)} sizes, {target.stat().st_size} bytes")
    app.quit()


if __name__ == "__main__":
    main()
