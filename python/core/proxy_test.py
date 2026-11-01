"""
proxy_test.py —— M2 自检（无图形界面）
用法：.venv/bin/python -m core.proxy_test
作用：在 deepin 桌面上验证"系统代理开/关"是否真的生效。
注意：gsettings 只在 deepin 的图形会话里有效；纯 SSH/服务器环境读不到桌面配置，属正常。
"""
import sys
from core import proxy


def main():
    print("=== clashDP  M2 系统代理 自检 ===")
    print("当前系统代理模式:", proxy.get_proxy_mode())

    print("\n[1] 开启系统代理（指向 mihomo 端口 %d）..." % proxy.MIXED_PORT)
    for code, out in proxy.enable_proxy():
        if code != 0:
            print("   提示:", out)
    print("    开启后模式:", proxy.get_proxy_mode())

    print("\n[2] 关闭系统代理...")
    code, out = proxy.disable_proxy()
    if code != 0:
        print("   提示:", out)
    print("    关闭后模式:", proxy.get_proxy_mode())

    print("\n如果模式在 '手动'(manual) 和 '无'(none) 之间正确切换，M2 系统代理部分通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
