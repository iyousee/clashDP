#!/usr/bin/env python3
"""
make_icon.py —— 生成应用图标 clashdp.png（256x256）
样式与托盘图标保持一致：蓝色圆角方块 + 白色 "C"。
打包时会把这张图装到 /usr/share/icons/hicolor/256x256/apps/clashdp.png，
启动器里就能看到图标了。
"""
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QPainter, QPixmap)

SIZE = 256


def make(path):
    pix = QPixmap(SIZE, SIZE)
    pix.fill(QColor(0, 0, 0, 0))  # 透明底

    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)

    # 圆角方块背景（和托盘图标同一个蓝 #2d8cf0）
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#2d8cf0"))
    p.drawRoundedRect(8, 8, SIZE - 16, SIZE - 16, 56, 56)

    # 白色 "C"
    p.setPen(QColor("#ffffff"))
    font = QFont()
    font.setBold(True)
    font.setPixelSize(int(SIZE * 0.6))
    p.setFont(font)
    p.drawText(pix.rect(), Qt.AlignCenter, "C")
    p.end()

    ok = pix.save(path, "PNG")
    print("图标已生成：%s (%s)" % (path, "成功" if ok else "失败"))
    return ok


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)  # QPixmap 需要先有 QGuiApplication
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clashdp.png")
    sys.exit(0 if make(out) else 1)
