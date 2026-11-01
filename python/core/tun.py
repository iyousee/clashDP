"""
tun.py —— TUN 模式权限管理（M8 模块）
作用：TUN 让内核接管"整机流量"（全局透明代理，APP 不用改代理设置也能走代理），
      但 Linux 只允许有特权（CAP_NET_ADMIN）的程序创建虚拟网卡。
      这个模块负责：检查有没有权限、一键授权、失败时给出兜底命令。

大白话：TUN 相当于给内核装一张"虚拟网卡"，让所有流量先流进内核。
        Linux 不允许普通程序随便建网卡，所以要给 mihomo 这个文件单独发一张
        "权限凭证"（setcap）。凭证贴在文件上，换内核文件后要重新贴。
"""
import os
import subprocess
from core import config

# TUN 需要的能力（依据 mihomo 官方 systemd 服务模板 + 社区面板实践）：
#   cap_net_admin        —— 创建/配置虚拟网卡、改系统路由（TUN 的关键）
#   cap_net_raw          —— 原始套接字（部分 TUN 栈/流量接管场景需要）
#   cap_net_bind_service —— 绑定 53 等特权端口（DNS 相关）
NEEDED_CAPS = ("cap_net_admin", "cap_net_raw", "cap_net_bind_service")


def binary_path():
    """返回 mihomo 二进制路径。"""
    return config.get_mihomo_binary()


def manual_command(path=None):
    """返回"手动授权"命令（自动授权失败时复制到终端执行）。"""
    path = path or binary_path()
    return "sudo setcap cap_net_admin,cap_net_raw,cap_net_bind_service=+ep %s" % path


def _parse_getcap(out):
    """
    解析 getcap 的输出，返回小写能力名集合。
    输出形如：/home/x/mihomo cap_net_admin,cap_net_bind_service=ep
    没有能力时输出为空字符串。
    """
    caps = set()
    if "=" not in out:
        return caps
    left = out.split("=", 1)[0]
    token = left.rsplit(" ", 1)[-1]      # 去掉前面的文件路径
    for c in token.split(","):
        c = c.strip().lower()
        if c.startswith("cap_"):
            caps.add(c)
    return caps


def get_capabilities(path=None):
    """读取 mihomo 已有的能力集合；getcap 不存在或读取失败返回空 set。"""
    path = path or binary_path()
    try:
        r = subprocess.run(["getcap", path], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return set()
    return _parse_getcap((r.stdout or "") + (r.stderr or ""))


def has_tun_capability(path=None):
    """是否已具备 CAP_NET_ADMIN（TUN 的关键权限）。"""
    return "cap_net_admin" in get_capabilities(path)


def status(path=None):
    """
    返回一份权限状态，界面可直接展示：
      {"ok": bool, "binary": 路径, "caps": [能力...], "command": 手动命令}
    """
    path = path or binary_path()
    caps = get_capabilities(path)
    return {
        "ok": "cap_net_admin" in caps,
        "binary": path,
        "caps": sorted(caps),
        "command": manual_command(path),
    }


def grant_capability(path=None, timeout=90):
    """
    尝试自动授权（需要管理员身份）。依次尝试：
      1) pkexec —— 桌面会弹系统认证框（推荐，deepin 有 polkit）
      2) sudo -n —— 已经缓存过 sudo 时可用
    返回 (是否成功, 说明文字)；都失败时把"手动命令"一起带回去。
    注意：沙箱 / SSH / 无桌面会话时必然失败，属正常现象，用返回的命令手动执行即可。
    """
    path = path or binary_path()
    if not os.path.isfile(path):
        return False, "找不到内核文件：%s" % path

    cmd = ["setcap", "cap_net_admin,cap_net_raw,cap_net_bind_service=+ep", path]
    tried = []
    for prefix, name in ((["pkexec"], "pkexec"), (["sudo", "-n"], "sudo -n")):
        try:
            r = subprocess.run(prefix + cmd, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            tried.append("%s 不可用" % name)
            continue
        except subprocess.TimeoutExpired:
            tried.append("%s 超时" % name)
            continue
        if r.returncode == 0:
            return True, "已授予 TUN 权限（%s）" % name
        err = (r.stderr or r.stdout or "").strip()
        tried.append("%s: %s" % (name, err or ("退出码 %d" % r.returncode)))

    return False, (
        "自动授权失败：\n" + "\n".join(tried) +
        "\n\n请在终端手动执行一次下面的命令（只需一次；以后换内核文件要重新执行）：\n"
        + manual_command(path)
    )
