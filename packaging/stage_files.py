#!/usr/bin/env python3
"""
stage_files.py —— 打包时"摆文件"的助手
============================================================
为什么不用 cp：要精确挑出"程序真正需要的文件"，把 PySide6 里
用不上的大件（WebEngine 浏览器内核、QML、多国翻译、开发工具）挡在门外。
在复制阶段就过滤，包目录里根本不会产生多余文件，也就不需要事后批量删除。

用法：
  python3 stage_files.py code <源码目录 python/> <目标 opt/clashDP>
  python3 stage_files.py deps <site-packages> <目标 opt/clashDP/lib>
"""
import os
import shutil
import sys

# ---------------------------------------------------------------- 需要的包
NEEDED_PACKAGES = {
    "PySide6",             # 图形界面
    "shiboken6",           # PySide6 的底层绑定层（必需）
    "requests",            # 调 mihomo 的 REST 接口
    "urllib3",             # requests 依赖
    "certifi",             # requests 的 HTTPS 证书
    "idna",                # requests 依赖
    "charset_normalizer",  # requests 依赖
    "yaml",                # 读写 config.yaml
    "_yaml",               # PyYAML 的 C 加速模块
}

NEEDED_DISTINFO = (
    "PySide6", "shiboken6", "requests", "urllib3",
    "certifi", "idna", "charset_normalizer", "pyyaml",
)

SKIP_DIRS = {"__pycache__", ".pytest_cache"}

# ------------------------------------------------- PySide6 里到底要留什么
# 我们只 import 了这三个模块，其余 .so 一个都不会被加载
PYSIDE_KEEP_MODULES = ("QtCore.abi3", "QtGui.abi3", "QtWidgets.abi3", "libpyside6.abi3")

# PySide6/Qt 下只保留这三个子目录
QT_KEEP_TOP = {"lib", "plugins", "translations"}

# Qt 插件的子目录白名单（其余全是 QML/3D/多媒体相关的）
PLUGIN_KEEP_DIRS = {
    "platforms",              # 把窗口画到屏幕上（xcb）
    "imageformats",           # png/svg 图标解码
    "iconengines",
    "platformthemes",         # deepin/gtk 主题
    "platforminputcontexts",  # 输入法（中文输入必需）
    "styles",
    "xcbglintegrations",
    "tls",
    "egldeviceintegrations",
}

# 平台插件只留三个（xcb 是正式用的，另两个是极小体积的无头兜底）
PLATFORM_PLUGINS = ("libqxcb.so", "libqoffscreen.so", "libqminimal.so")

# Qt 翻译只留中文（消息框的"确定/取消"要用）
KEEP_TRANSLATIONS = {"qtbase_zh_CN.qm", "qt_zh_CN.qm"}

# Qt/lib 里明确用不上的大块头库（按前缀匹配）
LIB_SKIP_PREFIX = (
    "libQt6WebEngine", "libQt6Quick", "libQt6Qml", "libQt6QmlModels",
    "libQt6QmlWorkerScript", "libQt6QmlCompiler", "libQt6QmlLocalStorage",
    "libQt63D", "libQt6Pdf", "libQt6Designer", "libQt6Multimedia",
    "libQt6Charts", "libQt6ShaderTools", "libQt6DataVisualization",
    "libQt6Graphs", "libQt6Bluetooth", "libQt6Nfc", "libQt6Sql",
    "libQt6Test", "libQt6Help", "libQt6RemoteObjects", "libQt6Sensors",
    "libQt6SerialPort", "libQt6SpatialAudio", "libQt6Location",
    "libQt6Positioning", "libQt6TextToSpeech", "libQt6VirtualKeyboard",
    "libQt6Scxml", "libQt6StateMachine", "libQt6UiTools", "libQt6WebSockets",
    "libQt6WebChannel", "libQt6HttpServer", "libQt6PdfWidgets",
    "libQt6SensorsQuick", "libQt6Concurrent", "libQt6WlShellIntegration",
    "libQt6WaylandClient", "libQt6WaylandCompositor",
)


def copy_file(src, dst):
    shutil.copy2(src, dst)
    if os.access(src, os.X_OK):
        os.chmod(dst, 0o755)


def copy_tree(src, dst):
    """普通包：整目录复制（跳过缓存）。"""
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel = os.path.relpath(root, src)
        target = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(target, exist_ok=True)
        for name in files:
            if name.endswith((".pyc", ".pyo")):
                continue
            copy_file(os.path.join(root, name), os.path.join(target, name))


def copy_pyside(src, dst):
    """PySide6 专用：边走边筛，只把真正要加载的文件搬过去。"""
    kept = 0
    for root, dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        parts = [] if rel == "." else rel.split(os.sep)

        # --- 目录剪枝 ---
        keep = []
        for d in dirs:
            if d in SKIP_DIRS:
                continue
            path = parts + [d]
            if path[0] == "Qt":
                if len(path) == 2 and d not in QT_KEEP_TOP:
                    continue                       # Qt/qml、Qt/resources 等整块跳过
                if len(path) == 3 and path[1] == "plugins" and d not in PLUGIN_KEEP_DIRS:
                    continue                       # 用不上的插件类别
            keep.append(d)
        dirs[:] = keep

        target = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(target, exist_ok=True)

        for name in files:
            if name.endswith((".pyc", ".pyo", ".pyi", ".pdb")):
                continue                           # 类型提示/调试符号，运行时不需要
            path = parts + [name]
            skip = False

            if path[0] == "Qt":
                if len(path) >= 2 and path[1] == "lib":
                    if name.startswith(LIB_SKIP_PREFIX):
                        skip = True
                elif len(path) >= 2 and path[1] == "translations":
                    if name not in KEEP_TRANSLATIONS:
                        skip = True
                elif len(path) >= 3 and path[1] == "plugins" and path[2] == "platforms":
                    if not name.startswith(PLATFORM_PLUGINS):
                        skip = True
            else:
                # PySide6 顶层：.so 只留三个界面模块 + 绑定层；
                # 没有扩展名的可执行文件是 lupdate/lrelease 之类开发工具，一律不要
                if ".so" in name:
                    if not name.startswith(PYSIDE_KEEP_MODULES):
                        skip = True
                elif "." not in name:
                    skip = True

            if skip:
                continue
            copy_file(os.path.join(root, name), os.path.join(target, name))
            kept += 1

    print("  PySide6 已筛出 %d 个文件（WebEngine/QML/翻译/开发工具全部未复制）" % kept)


def stage_code(src_root, dst_root):
    total = 0
    for pkg in ("app", "core"):
        s = os.path.join(src_root, pkg)
        if not os.path.isdir(s):
            print("  ✗ 找不到源码目录：%s" % s)
            return 1
        copy_tree(s, os.path.join(dst_root, pkg))
        for _root, _dirs, files in os.walk(os.path.join(dst_root, pkg)):
            total += len(files)
    print("  已放入程序代码：%d 个文件（app/ core/）" % total)
    return 0


def stage_deps(sp_src, lib_dst):
    if not os.path.isdir(sp_src):
        print("  ✗ 找不到 site-packages：%s" % sp_src)
        return 1
    os.makedirs(lib_dst, exist_ok=True)
    picked = []
    for name in sorted(os.listdir(sp_src)):
        full = os.path.join(sp_src, name)
        if os.path.isdir(full) and name in NEEDED_PACKAGES:
            if name == "PySide6":
                copy_pyside(full, os.path.join(lib_dst, name))
            else:
                copy_tree(full, os.path.join(lib_dst, name))
            picked.append(name)
        elif os.path.isfile(full) and name.endswith(".so") and not name.startswith("pip"):
            copy_file(full, os.path.join(lib_dst, name))
            picked.append(name)
        elif name.endswith(".dist-info") and name.startswith(NEEDED_DISTINFO):
            copy_tree(full, os.path.join(lib_dst, name))
            picked.append(name)
    print("  已放入依赖：%s" % ", ".join(picked))
    return 0


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    mode, src, dst = sys.argv[1], sys.argv[2], sys.argv[3]
    if mode == "code":
        return stage_code(src, dst)
    if mode == "deps":
        return stage_deps(src, dst)
    print("未知模式：", mode)
    return 2


if __name__ == "__main__":
    sys.exit(main())
