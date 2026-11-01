#!/bin/bash
# =============================================================================
# verify_deb.sh —— 不安装、先验收 .deb 包
#
# 干三件事：
#   1. 检查包里关键文件是否齐全（内核、依赖库、启动器、桌面项、图标）
#   2. 检查控制信息（版本号、依赖、安装后脚本权限）
#   3. 把包解开到一个临时目录，用里面的库真实启动一次界面（无头模式），
#      证明"装到别人机器上也能跑"，而不是只能在本机跑
#
# 用法：./verify_deb.sh [deb 文件路径]（不填则取 dist-deb 里最新的）
# =============================================================================
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

DEB="${1:-}"
if [ -z "$DEB" ]; then
    DEB="$(ls -t "$HERE"/../dist-deb/*.deb 2>/dev/null | head -1)"
fi
if [ ! -f "$DEB" ]; then
    echo "✗ 找不到 .deb，请先运行 ./build_deb.sh"
    exit 1
fi

echo "验收对象：$DEB"
echo "大小：$(du -h "$DEB" | cut -f1)"
echo

fail=0
# 先把包内文件清单取一次存下来：比每次重新扫包快，也避免管道提前关闭导致误判
LIST="$HERE/.tmp/pkglist.txt"
mkdir -p "$HERE/.tmp"
dpkg-deb -c "$DEB" 2>/dev/null | awk '{print $6}' > "$LIST" || true

check() {  # check <路径> <说明>
    if grep -qx "$1" "$LIST"; then
        echo "  ✓ $2"
    else
        echo "  ✗ 缺文件：$1（$2）"
        fail=$((fail + 1))
    fi
}

echo "[1] 关键文件"
check "./opt/clashDP/mihomo"                                        "mihomo 内核"
check "./opt/clashDP/geoip.dat"                                     "GeoIP 库"
check "./opt/clashDP/geosite.dat"                                   "GeoSite 库"
check "./opt/clashDP/app/main.py"                                   "程序入口"
check "./opt/clashDP/core/kernel.py"                                "内核管理模块"
check "./opt/clashDP/lib/PySide6/QtWidgets.abi3.so"                 "Qt 界面库"
check "./opt/clashDP/lib/PySide6/Qt/plugins/platforms/libqxcb.so"   "xcb 平台插件"
check "./opt/clashDP/lib/PySide6/Qt/lib/libQt6Core.so.6"            "Qt 核心库"
check "./opt/clashDP/clashdp-launcher.py"                           "启动器"
check "./usr/bin/clashdp"                                           "命令行入口"
check "./usr/share/applications/clashdp.desktop"                    "桌面项"
check "./usr/share/icons/hicolor/256x256/apps/clashdp.png"          "应用图标"

echo
echo "[2] 包信息"
dpkg-deb -f "$DEB" 2>/dev/null | sed -n '1,10p' | sed 's/^/  /'
echo "  包内文件数：$(wc -l < "$LIST")"

echo
echo "[3] 解包并真实启动一次界面（无头模式）"
TMP="$HERE/.tmp/verify"
# 上次的解包目录改名归档，保证这次是干净的
if [ -d "$TMP" ]; then mv "$TMP" "$HERE/.tmp/verify_$(date +%H%M%S)" 2>/dev/null || true; fi
mkdir -p "$TMP"
dpkg-deb -x "$DEB" "$TMP"
CLASHDP_PACKAGED=1 QT_QPA_PLATFORM=offscreen /usr/bin/python3 -c "
import sys
sys.path.insert(0, '$TMP/opt/clashDP/lib')
sys.path.insert(0, '$TMP/opt/clashDP')
from PySide6.QtWidgets import QApplication
import PySide6
app = QApplication([])
from app.ui.main_window import MainWindow
w = MainWindow()
tabs = [w.tabs.tabText(i) for i in range(w.tabs.count())]
print('      PySide6 版本:', PySide6.__version__)
print('      标签页:', ' / '.join(tabs))
assert len(tabs) == 6, '标签页数量不对'
print('      ✓ 界面构建成功')
" || { echo "  ✗ 解包后启动失败"; fail=$((fail + 1)); }

# 内核能不能执行（只问版本号，不联网）
echo
echo "[4] 包内内核可执行性"
if [ -x "$TMP/opt/clashDP/mihomo" ]; then
    ver="$("$TMP/opt/clashDP/mihomo" -v 2>&1 | head -1)"
    echo "  ✓ 内核可执行：$ver"
else
    echo "  ✗ mihomo 没有可执行权限"
    fail=$((fail + 1))
fi

echo
echo "[5] 启动器链路（模拟点开桌面图标后的完整启动过程）"
# 直接跑包里的启动器：它会自己设置路径和"已打包"标记，和真实安装后一模一样。
# 用 timeout 限时 5 秒——如果 5 秒后还在跑，说明界面起来了（Qt 事件循环不会自己退出）。
QT_QPA_PLATFORM=offscreen timeout 5 /usr/bin/python3 \
    "$TMP/opt/clashDP/clashdp-launcher.py" > "$HERE/.tmp/launcher.log" 2>&1
code=$?
if [ $code -eq 124 ]; then
    echo "  ✓ 启动器工作正常（程序持续运行中，被 timeout 正常终止）"
else
    echo "  ✗ 启动器异常退出（退出码 $code）"
    sed -n '1,10p' "$HERE/.tmp/launcher.log" | sed 's/^/      /'
    fail=$((fail + 1))
fi

echo
if [ "$fail" -eq 0 ]; then
    echo "================ 验收通过 ================"
    exit 0
else
    echo "================ 有 $fail 项未通过 ================"
    exit 1
fi
