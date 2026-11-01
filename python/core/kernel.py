"""
kernel.py —— mihomo 内核管理（M1 模块）
作用：找到 mihomo 二进制、生成 config.yaml、启动/停止/重启内核进程、健康检查。
大白话：这是"指挥内核"的模块，APP 其他功能都靠它来开关代理内核。
"""
import os
import shutil
import subprocess
import secrets
import tempfile
import time
from core import config

# 控制口（本机专用，APP 通过它发指令给内核）和混合端口（系统代理指向这里）
CONTROLLER_ADDR = "127.0.0.1:9090"
MIXED_PORT = 7890

# 内核运行日志文件：内核的输出写到这里，启动失败时可以看它排查原因
LOG_FILE = os.path.join(config.get_user_config_dir(), "mihomo.log")


def _build_tun(enable):
    """
    生成 TUN 段配置（M8）。
    关闭时只写 enable:false，避免多留无用键；开启时给一套稳妥的默认值。
    """
    if not enable:
        return {"enable": False}
    return {
        "enable": True,
        "stack": "mixed",               # system / gvisor / mixed，mixed 兼容性最好
        "device": "clashdp-tun",        # 虚拟网卡名
        "auto-route": True,             # 自动改系统路由指向 TUN（透明代理的关键）
        "auto-detect-interface": True,  # 自动识别默认网卡
        "dns-hijack": ["any:53"],       # 劫持所有 DNS，防止 DNS 泄漏
        "mtu": 9000,
    }


def build_config(secret=None, tun_enable=None):
    """
    生成 mihomo 的配置字典（Python 字典）。
    订阅模块(M3)之后会把节点、策略组、规则填进 proxies/proxy-groups/rules。
    tun_enable: 是否开启 TUN。传 None 时自动读用户设置 settings.json，
                这样订阅重建配置时也能保留 TUN 开关，不会莫名被关掉。
    """
    if secret is None:
        # 用"稳定密钥"：优先沿用现有配置/设置里的，避免重建配置时换钥匙导致 401
        secret = config.get_or_create_secret()
    if tun_enable is None:
        tun_enable = bool(config.load_settings().get("tun_enabled", False))

    cfg = {
        "mixed-port": MIXED_PORT,          # HTTP+SOCKS 混合端口，系统代理和 APP 都指它
        "allow-lan": False,                # 不允许局域网其他设备连（更安全）
        "mode": "rule",                    # 规则模式（也可改成 global 全局 / direct 直连）
        "log-level": "info",
        "external-controller": CONTROLLER_ADDR,  # 控制口地址
        "secret": secret,                  # 控制口密钥
        "dns": {
            "enable": True,
            "enhanced-mode": "fake-ip",     # 假 IP 模式，分流更准
            "fake-ip-range": "198.18.0.1/16",
            "nameserver": ["223.5.5.5", "119.29.29.29"],  # 国内公共 DNS
        },
        "tun": _build_tun(tun_enable),     # TUN 全局透明代理（M8）
        "proxies": [],                     # 节点列表（订阅填充）
        "proxy-groups": [],                # 策略组（订阅填充）
        "rules": [],                       # 规则（订阅填充）
    }
    return cfg


def write_config(cfg, path=None):
    """
    把配置字典写成 config.yaml 文件。
    注意：yaml 这个库是"用到才导入"，这样即使没装 PyYAML，本模块也能被 import（方便沙箱测试）。
    """
    import yaml  # 延迟导入：只有真正写配置时才需要
    path = path or config.get_config_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    return path


def find_mihomo():
    """返回 mihomo 二进制路径；找不到返回 None。"""
    p = config.get_mihomo_binary()
    if os.path.isfile(p) and os.access(p, os.X_OK):
        return p
    return None


# 内核运行时会在"工作目录(-d)"里找地理库；我们的 .dat 放在内核目录，
# 所以启动前把它们链接过去，否则 GEOIP/GEOSITE 规则会失效。
_GEO_NAMES = ("geoip.dat", "geosite.dat", "geoip.metadb", "GeoIP.dat", "GeoSite.dat")


def ensure_geodata(work_dir):
    """
    把内核目录里的地理库(geoip.dat/geosite.dat)链接到工作目录。
    已经有就不动；不支持软链接（如跨盘）就退化成复制。
    """
    src_dir = config.get_geoip_files()
    os.makedirs(work_dir, exist_ok=True)
    for name in _GEO_NAMES:
        src = os.path.join(src_dir, name)
        dst = os.path.join(work_dir, name)
        if not os.path.isfile(src) or os.path.exists(dst):
            continue
        try:
            os.symlink(src, dst)
        except OSError:
            try:
                shutil.copy2(src, dst)
            except OSError:
                pass  # 链接/复制都失败就算了，不影响主流程


def verify_config(config_path):
    """
    用内核自己的校验模式检查配置文件：`mihomo -t -d <目录> -f <文件>`。
    返回 (是否通过, 内核输出)。找不到内核时视为通过（跳过校验）。
    """
    binary = find_mihomo()
    if not binary:
        return True, "（未找到内核，跳过配置校验）"
    work_dir = config.get_user_config_dir()
    ensure_geodata(work_dir)
    try:
        r = subprocess.run(
            [binary, "-t", "-d", work_dir, "-f", config_path],
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        return False, "配置校验超时（30 秒）"
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    return r.returncode == 0, out


def verify_config_dict(cfg):
    """
    校验"还没落盘"的配置字典：先写临时文件，再交给内核校验。
    返回 (是否通过, 内核输出)。
    """
    import yaml
    fd, tmp = tempfile.mkstemp(suffix=".yaml", prefix="clashdp_check_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
        return verify_config(tmp)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


class ConfigError(RuntimeError):
    """配置没通过内核校验（多半是订阅生成的规则引用了不存在的东西）。"""


def start_kernel(verify=True, timeout=4.0, precheck=True):
    """
    启动 mihomo 子进程。
    返回 subprocess.Popen 对象（后续用它来停止）；找不到内核或启动失败都抛异常。
    verify=True 时：启动后确认内核真的活下来了——若几秒内就退出，说明启动失败，
                     会把内核日志读出来一起抛给你看（不再像以前那样"无反应"）。
    precheck=True 时：启动前先用 `mihomo -t` 校验配置，
                     配置有问题就抛 ConfigError（界面可据此自动重新生成配置）。
    """
    binary = find_mihomo()
    if not binary:
        raise FileNotFoundError(
            "未找到 mihomo，请把它放到：" + config.get_mihomo_dir()
        )

    # 确保配置文件存在（没有就先生成一份默认配置）
    cfg_path = config.get_config_file()
    if not os.path.isfile(cfg_path):
        write_config(build_config(), cfg_path)

    # 启动前先校验配置：配置错了早点说清楚，不用等内核崩溃再去猜
    if precheck:
        ok, log = verify_config(cfg_path)
        if not ok:
            raise ConfigError("配置文件没通过内核校验：\n" + log)

    work_dir = config.get_user_config_dir()
    os.makedirs(work_dir, exist_ok=True)
    ensure_geodata(work_dir)   # 让 GEOIP/GEOSITE 规则有地理库可用

    # 把内核的输出写进日志文件（不再丢进 DEVNULL 让你看不到报错）
    logf = open(LOG_FILE, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [binary, "-d", work_dir, "-f", cfg_path],
        stdout=logf,
        stderr=subprocess.STDOUT,
    )

    # 启动后短暂确认它没立刻崩溃：若在 timeout 内退出，说明启动失败
    if verify:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if proc.poll() is not None:
                # 进程已经退出 -> 启动失败，把日志尾巴读出来
                try:
                    logf.close()
                except Exception:
                    pass
                raise RuntimeError(
                    "mihomo 启动后立刻退出（启动失败）。\n"
                    "常见原因：配置里的规则/RULE-SET 引用了不存在的东西、端口 7890 被别的程序占用。\n"
                    "最后日志：\n" + _read_log_tail())
            time.sleep(0.2)
    return proc


def stop_kernel(proc):
    """优雅停止内核；卡住就强制杀掉。"""
    if proc is None:
        return
    if proc.poll() is None:        # poll() 为 None 表示还在运行
        proc.terminate()           # 先发终止信号
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()            # 5 秒没退出就强杀


def is_running(proc):
    """判断内核是否还在运行。"""
    return proc is not None and proc.poll() is None


def kernel_log_path():
    """返回内核日志文件路径（界面排错时展示给用户）。"""
    return LOG_FILE


def _read_log_tail(n=50):
    """读取内核日志最后 n 行，用于报错时展示原因。"""
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-n:]) or "（日志为空）"
    except FileNotFoundError:
        return "（没有日志文件）"
