#!/bin/bash
# =============================================================================
# build_deb.sh —— 一键把 clashDP 打成 .deb 安装包
#
# 用法：
#   ./build_deb.sh              打包，版本号默认 1.0.0
#   ./build_deb.sh 1.0.1        指定版本号
#
# 产物：
#   ../dist-deb/clashdp_<版本>_arm64.deb
#
# 大白话：这个脚本干的就是"把该放的文件按 Debian 规定的目录摆好，
#        然后交给 dpkg-deb 压成一个包"，不需要装 debhelper 等额外工具。
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
VERSION="${1:-1.0.0}"
ARCH="arm64"
SRC="$HERE/../python"
OUT="$HERE/../dist-deb"
WORK="$HERE/.tmp"
BUILD="$WORK/build/clashdp_${VERSION}_${ARCH}"
PKG="$BUILD/opt/clashDP"

# 自动找出 venv 的 site-packages（Python 小版本可能不同，不写死）
SP_SRC="$(ls -d "$SRC"/.venv/lib/python3*/site-packages 2>/dev/null | head -1)"
if [ -z "${SP_SRC:-}" ]; then
    echo "✗ 找不到 $SRC/.venv/lib/python3*/site-packages"
    echo "  请先在 $SRC 目录下建好虚拟环境（见开发阶段的说明）。"
    exit 1
fi

echo "=============================================="
echo " 打包 clashDP v$VERSION ($ARCH)"
echo "=============================================="

# 上一轮的构建目录不删除，直接改名归档（避免误删，也保证这次是全新的一份）
if [ -d "$WORK/build" ]; then
    OLD="$WORK/old_$(date +%H%M%S)"
    mv "$WORK/build" "$OLD" 2>/dev/null || true
    echo "      上一轮构建已归档为 packaging/.tmp/$(basename "$OLD")（可手动删除释放空间）"
fi

mkdir -p "$PKG/lib" "$BUILD/DEBIAN" \
         "$BUILD/usr/bin" \
         "$BUILD/usr/share/applications" \
         "$BUILD/usr/share/icons/hicolor/256x256/apps"

# ---------- 1. 程序代码 ----------
echo "[1/6] 拷贝程序代码 (app/ core/) ..."
/usr/bin/python3 "$HERE/stage_files.py" code "$SRC" "$PKG" | sed 's/^/    /'

# ---------- 2. Python 依赖 ----------
echo "[2/6] 拷贝 Python 依赖（只挑真正用到的包）..."
/usr/bin/python3 "$HERE/stage_files.py" deps "$SP_SRC" "$PKG/lib" | sed 's/^/    /'

# ---------- 3. 精简 PySide6 ----------
echo "[3/6] 精简 PySide6（删掉 WebEngine/QML/多国翻译等用不上的部分）..."
/usr/bin/python3 "$HERE/prune_pyside.py" "$PKG/lib" | sed 's/^/      /'

# ---------- 4. 内核与地理库 ----------
echo "[4/6] 拷贝 mihomo 内核与 GeoIP/GeoSite ..."
install -m 755 "$SRC/data/mihomo/mihomo"      "$PKG/mihomo"
install -m 644 "$SRC/data/mihomo/geoip.dat"   "$PKG/geoip.dat"
install -m 644 "$SRC/data/mihomo/geosite.dat" "$PKG/geosite.dat"

# ---------- 5. 启动器 / 桌面项 / 图标 ----------
echo "[5/6] 安装启动脚本、桌面项与图标 ..."
install -m 644 "$HERE/clashdp-launcher.py" "$PKG/clashdp-launcher.py"
install -m 755 "$HERE/clashdp"             "$BUILD/usr/bin/clashdp"
install -m 644 "$HERE/clashdp.desktop"     "$BUILD/usr/share/applications/clashdp.desktop"

if [ ! -f "$HERE/clashdp.png" ]; then
    echo "      图标不存在，正在生成 ..."
    # 用"刚放进包里的那套依赖"来画图标，顺便验证这些库真的能用
    PYTHONPATH="$PKG/lib" QT_QPA_PLATFORM=offscreen CLASHDP_PACKAGED=1 \
        /usr/bin/python3 "$HERE/make_icon.py" | sed 's/^/      /'
fi
install -m 644 "$HERE/clashdp.png" \
    "$BUILD/usr/share/icons/hicolor/256x256/apps/clashdp.png"

# ---------- 6. 生成 DEBIAN 控制信息并打包 ----------
echo "[6/6] 生成包信息并压缩 ..."
SIZE="$(du -sk "$BUILD" | cut -f1)"
/usr/bin/python3 - "$HERE/debian/control" "$BUILD/DEBIAN/control" "$VERSION" "$SIZE" <<'PY'
import sys
src, dst, ver, size = sys.argv[1:5]
text = open(src, encoding="utf-8").read()
text = text.replace("@VERSION@", ver).replace("@SIZE@", size)
open(dst, "w", encoding="utf-8").write(text)
PY
install -m 755 "$HERE/debian/postinst" "$BUILD/DEBIAN/postinst"
install -m 755 "$HERE/debian/postrm"   "$BUILD/DEBIAN/postrm"

mkdir -p "$OUT"
DEB="$OUT/clashdp_${VERSION}_${ARCH}.deb"
# -Zxz：用 xz 压缩（体积最小）；--root-owner-group：文件属主统一成 root
dpkg-deb --root-owner-group -Zxz --build "$BUILD" "$DEB" >/dev/null

echo
echo "✅ 打包完成：$DEB"
echo "   大小：$(du -h "$DEB" | cut -f1)"
echo "   安装：sudo dpkg -i \"$DEB\""
echo "   卸载：sudo dpkg -r clashdp      彻底删配置：sudo dpkg --purge clashdp"
