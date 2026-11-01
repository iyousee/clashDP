"""
tray.py —— 系统托盘（关窗后台、右键菜单）
作用：程序窗口关掉后，仍在后台运行；托盘图标右键可"显示/启动代理/停止代理/退出"。
大白话：这就是桌面右上角那个小图标，点它能控制整个程序。
"""
from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
from PySide6.QtCore import Signal, Qt
from app.ui.i18n import _


def _make_fallback_icon(size=64):
    """
    自绘一个兜底图标：蓝色圆角方块 + 白色 "C"（Clash 的首字母）。
    仅当系统找不到合适的主题图标时才用，保证托盘永远有图标（否则托盘可能不显示）。
    """
    pix = QPixmap(size, size)
    pix.fill(QColor(0, 0, 0, 0))  # 透明底
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    # 圆角方块背景
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#2d8cf0"))
    p.drawRoundedRect(4, 4, size - 8, size - 8, 14, 14)
    # 白色 "C"
    p.setPen(QColor("#ffffff"))
    font = QFont()
    font.setBold(True)
    font.setPixelSize(int(size * 0.6))
    p.setFont(font)
    p.drawText(pix.rect(), Qt.AlignCenter, "C")
    p.end()
    return QIcon(pix)


class TrayIcon(QSystemTrayIcon):
    # 定义托盘菜单触发的信号，由主窗口连接具体逻辑
    show_clicked = Signal()
    start_clicked = Signal()
    stop_clicked = Signal()
    quit_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # 图标：优先用系统主题的网络类图标，没有就自绘一个，避免"无图标"警告/托盘不显示
        icon = QIcon.fromTheme("network-vpn")
        if icon.isNull():
            icon = _make_fallback_icon()
        self.setIcon(icon)
        self.setToolTip("clashDP")
        self._build_menu()
        self.activated.connect(self._on_activated)  # 单击图标也能显示窗口

    def _build_menu(self):
        self.menu = QMenu()
        self.act_show = self.menu.addAction(_("显示窗口", "Show"))
        self.act_start = self.menu.addAction(_("启动代理", "Start Proxy"))
        self.act_stop = self.menu.addAction(_("停止代理", "Stop Proxy"))
        self.menu.addSeparator()
        self.act_quit = self.menu.addAction(_("退出", "Quit"))

        self.act_show.triggered.connect(self.show_clicked.emit)
        self.act_start.triggered.connect(self.start_clicked.emit)
        self.act_stop.triggered.connect(self.stop_clicked.emit)
        self.act_quit.triggered.connect(self.quit_clicked.emit)

        self.setContextMenu(self.menu)

    def retranslate(self):
        """切换语言时刷新菜单文字。"""
        self.act_show.setText(_("显示窗口", "Show"))
        self.act_start.setText(_("启动代理", "Start Proxy"))
        self.act_stop.setText(_("停止代理", "Stop Proxy"))
        self.act_quit.setText(_("退出", "Quit"))

    def _on_activated(self, reason):
        # 左键/双击：显示主窗口
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_clicked.emit()
