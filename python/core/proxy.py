"""
proxy.py —— 系统代理开关（deepin）
作用：通过 gsettings 把"整个系统的代理"指向 mihomo 的混合端口(7890)，或关闭系统代理。
大白话：这一层负责"系统走不走代理"。全局/规则切换请见 mihomo_api.set_mode（那是内核内部的路由模式）。

重要（deepin 实测）：deepin 把系统代理做成了"嵌套 schema"，每个协议是独立 schema：
    com.deepin.wrap.gnome.system.proxy.http   -> 键 host / port
    com.deepin.wrap.gnome.system.proxy.https  -> 键 host / port
    com.deepin.wrap.gnome.system.proxy.socks  -> 键 host / port
总开关在父 schema 的 mode 键：com.deepin.wrap.gnome.system.proxy mode 'manual'/'none'
"""
import subprocess
from core import config
from core.kernel import MIXED_PORT

# 父 schema（管总开关 mode）
SCHEMA = "com.deepin.wrap.gnome.system.proxy"


class ProxyError(Exception):
    """系统代理设置失败时抛出，方便界面把真实原因弹给用户看。"""
    pass


def _run_gsettings(args):
    """执行一条 gsettings 命令，返回 (返回码, 输出文本)。"""
    try:
        r = subprocess.run(["gsettings"] + args, capture_output=True,
                           text=True, timeout=10)
        return r.returncode, (r.stdout + r.stderr).strip()
    except FileNotFoundError:
        # 沙箱/SSH 里可能没有 gsettings 命令
        return -1, "gsettings 命令不存在（只能在 deepin 桌面会话里运行）"


def _require_ok(code, out, action):
    """gsettings 返回非 0 就抛 ProxyError，把真实报错带出来。"""
    if code != 0:
        raise ProxyError("设置系统代理失败（%s）：\n%s" % (action, out))


def enable_proxy(host="127.0.0.1", port=MIXED_PORT):
    """
    开启系统代理：把 http/https/socks 都指向 mihomo 的混合端口(7890)。
    混合端口同时支持 HTTP 和 SOCKS5，所以三个协议填同一个端口即可。

    注意 gsettings 语法是：gsettings set <schema> <key> <value>
    （"set" 必须放在 schema 前面），每个协议是嵌套 schema：
        gsettings set com.deepin.wrap.gnome.system.proxy.http  host 127.0.0.1
        gsettings set com.deepin.wrap.gnome.system.proxy.http  port 7890
        ... https / socks 同理
    最后把总开关切到 manual。
    """
    for proto in ("http", "https", "socks"):
        schema = "%s.%s" % (SCHEMA, proto)
        c1, o1 = _run_gsettings(["set", schema, "host", host])
        _require_ok(c1, o1, "%s host" % proto)
        c2, o2 = _run_gsettings(["set", schema, "port", str(port)])
        _require_ok(c2, o2, "%s port" % proto)
    # 最后把总开关切到 manual（手动）
    c, o = _run_gsettings(["set", SCHEMA, "mode", "manual"])
    _require_ok(c, o, "mode")
    return True


def disable_proxy():
    """关闭系统代理（mode 设为 none）。"""
    c, o = _run_gsettings(["set", SCHEMA, "mode", "none"])
    _require_ok(c, o, "mode")
    return True


def get_proxy_mode():
    """读取当前系统代理模式：'none' / 'manual' / 'auto'，读不到返回 None。"""
    code, out = _run_gsettings(["get", SCHEMA, "mode"])
    if code != 0:
        return None
    return out.strip().strip("'")   # gsettings 返回值带单引号，去掉
