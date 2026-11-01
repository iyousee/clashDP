#!/usr/bin/env python3
"""
prune_pyside.py —— PySide6 体积核算 / 瘦身工具
------------------------------------------------------------
大白话：PySide6 完整装完有 566MB，其中 166MB 是浏览器内核（WebEngine）、
50MB 是多国语言翻译、27MB 是 QML 相关——我们一个都用不上。

注意：正式的打包流程**不是靠这个脚本删文件**。打包时 stage_files.py
在"复制阶段"就把不需要的文件挡在门外了，包目录里根本不会产生多余的，
所以这里默认只做核算（看看还剩哪些可省的、包有多大）。

需要手工给一个完整的 site-packages 瘦身时，加 --delete 才会真删。

用法：
  python3 prune_pyside.py <site-packages 目录>            # 只核算，不删
  python3 prune_pyside.py <site-packages 目录> --delete    # 真删
"""
import os
import subprocess
import sys

DELETE = "--delete" in sys.argv

# ---- 黑名单：这些目录我们肯定用不上 ----
DROP_DIRS = [
    "PySide6/Qt/qml",            # QML 运行时（我们纯 Widgets）
    "PySide6/Qt/libexec",        # Qt 自带小工具
    "PySide6/Qt/metatypes",      # QML 类型信息
    "PySide6/Qt/resources",      # WebEngine 的 icudtl.dat / pak 资源
    "PySide6/Qt/scenegraph",     # Qt Quick 着色器
    "PySide6/Qt/plugins/webview",
    "PySide6/Qt/plugins/qmltooling",
    "PySide6/Qt/plugins/sceneparsers",
    "PySide6/Qt/plugins/renderers",
    "PySide6/Qt/plugins/geometryloaders",
    "PySide6/Qt/plugins/canbus",
    "PySide6/Qt/plugins/designer",
    "PySide6/Qt/plugins/sqldrivers",
    "PySide6/Qt/plugins/multimedia",
    "PySide6/Qt/plugins/assetimporters",
    "PySide6/Qt/plugins/position",
    "PySide6/Qt/plugins/sensors",
    "PySide6/Qt/plugins/texttospeech",
    "PySide6/Qt/plugins/virtualkeyboard",
    "PySide6/Qt/plugins/mediaservice",
    "PySide6/Qt/plugins/networkinformation",
]

KEEP_PLUGIN_DIRS = [
    "platforms", "imageformats", "iconengines", "platformthemes",
    "platforminputcontexts", "styles", "xcbglintegrations", "tls",
    "egldeviceintegrations",
]

KEEP_TRANSLATIONS = ("qtbase_zh_CN.qm", "qt_zh_CN.qm")

ROOT_MODULES = ["QtCore", "QtGui", "QtWidgets"]

KEEP_PLATFORM_PLUGINS = ("libqxcb.so", "libqoffscreen.so", "libqminimal.so")


def sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def needed_libs(path):
    """用 objdump 读出某个 ELF 文件依赖的库名列表。"""
    out = sh(["objdump", "-p", path])
    libs = []
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("NEEDED"):
            libs.append(line.split()[-1])
    return libs


def main():
    if len(sys.argv) < 2:
        print("用法: prune_pyside.py <site-packages 目录> [--delete]")
        return 1
    site = os.path.abspath(sys.argv[1])
    ps = os.path.join(site, "PySide6")
    qtlib = os.path.join(ps, "Qt", "lib")
    if not os.path.isdir(qtlib):
        print("找不到 PySide6，路径不对：", qtlib)
        return 1

    saved = 0

    # ---------- 1. 用不上的大目录 ----------
    dropped = []
    for rel in DROP_DIRS:
        p = os.path.join(site, rel)
        if os.path.isdir(p):
            saved += dir_size(p)
            dropped.append(rel)
            if DELETE:
                import shutil
                shutil.rmtree(p, ignore_errors=True)

    # ---------- 2. 非中文翻译 ----------
    tr = os.path.join(ps, "Qt", "translations")
    if os.path.isdir(tr):
        for name in os.listdir(tr):
            if name in KEEP_TRANSLATIONS:
                continue
            fp = os.path.join(tr, name)
            try:
                saved += os.path.getsize(fp)
                if DELETE:
                    os.remove(fp)
            except OSError:
                pass

    # ---------- 3. PySide6 自带的开发工具（lupdate 一个就 43MB）----------
    for name in os.listdir(ps):
        if name in ("Qt", "__pycache__", "include", "typesystems", "support"):
            continue
        p = os.path.join(ps, name)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            try:
                saved += os.path.getsize(p)
                if DELETE:
                    os.remove(p)
            except OSError:
                pass

    # ---------- 4. 从真正用到的模块出发，递归找依赖 ----------
    keep = set()

    def add(p):
        if p in keep or not os.path.isfile(p):
            return
        keep.add(p)
        for lib in needed_libs(p):
            for cand in (os.path.join(os.path.dirname(p), lib),
                         os.path.join(qtlib, lib)):
                if os.path.isfile(cand):
                    add(cand)
                    break

    for mod in ROOT_MODULES:
        add(os.path.join(ps, mod + ".abi3.so"))
    shib = os.path.join(site, "shiboken6")
    if os.path.isdir(shib):
        for f in os.listdir(shib):
            if f.endswith(".so"):
                add(os.path.join(shib, f))
    for d in KEEP_PLUGIN_DIRS:
        pd = os.path.join(ps, "Qt", "plugins", d)
        if not os.path.isdir(pd):
            continue
        for f in sorted(os.listdir(pd)):
            fp = os.path.join(pd, f)
            if not f.endswith(".so") or not os.path.isfile(fp):
                continue
            if d == "platforms" and not f.startswith(KEEP_PLATFORM_PLUGINS):
                continue
            add(fp)

    # ---------- 5. 没被依赖链碰到的 .so ----------
    unused = 0
    for root, _dirs, files in os.walk(ps):
        for f in files:
            if not f.endswith(".so") and ".so." not in f:
                continue
            fp = os.path.join(root, f)
            if fp in keep:
                continue
            try:
                saved += os.path.getsize(fp)
                unused += 1
                if DELETE:
                    os.remove(fp)
            except OSError:
                pass

    total = dir_size(ps)
    print("  未使用的 .so：%d 个" % unused)
    print("  本次省下：%.0f MB%s" % (saved / 1048576,
                                  "" if DELETE else "（仅核算，未实际删除）"))
    print("  PySide6 当前体积：%.0f MB" % (total / 1048576))
    return 0


if __name__ == "__main__":
    sys.exit(main())
