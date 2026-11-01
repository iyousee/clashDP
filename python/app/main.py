"""
main.py —— 程序入口（M5 真窗口版）
说明：创建 Qt 应用 -> 主窗口 -> 系统托盘；关窗不退出（最小化到托盘），
      只有托盘菜单的"退出"才真正关闭程序。
"""
import os
import sys

# ---------------------------------------------------------------------------
# 消除两条无害但扰人的 Qt 启动警告（必须在 import PySide6 之前设好环境变量）
# ---------------------------------------------------------------------------
# 1) 高分屏缩放策略：用环境变量设置最可靠，能彻底消除
#    "setHighDpiScaleFactorRoundingPolicy must be called before ..." 这条警告。
os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

# 2) deepin 默认会尝试加载自家的 dxcb 平台插件（仅 Qt5 版）；
#    而 PySide6 是 Qt6，加载不到会回退到 xcb 并打印警告。
#    既然 dxcb 本来就加载失败，干脆直接指定 xcb —— 既消除警告也不影响显示。
#    若系统已经是 wayland 等其它平台，则不覆盖，尊重原设置。
if os.environ.get("QT_QPA_PLATFORM", "").lower() in ("", "dxcb"):
    os.environ["QT_QPA_PLATFORM"] = "xcb"

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import Qt

from app.ui.main_window import MainWindow
from app.ui.tray import TrayIcon


def main():
    # 再保险一次：在创建 QApplication 实例之前设置高分屏策略
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    # 关掉"最后一个窗口关闭就退出程序"，改为交给托盘控制
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    window = MainWindow()
    tray = TrayIcon()
    window.tray = tray  # 让窗口能刷新托盘文字（语言切换时）

    # 连接托盘菜单到窗口的具体动作
    tray.show_clicked.connect(window.show_normal)
    tray.start_clicked.connect(window.start_all)
    tray.stop_clicked.connect(window.stop_all)
    tray.quit_clicked.connect(app.quit)

    tray.show()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
