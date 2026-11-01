"""
config.py —— 路径与设置管理
作用：统一管理"开发期"和"打包后"的文件位置，以及用户设置的读写。
大白话：告诉程序——mihomo 内核放在哪、用户配置存到哪、现在是在开发还是已打包。
"""
import os
import json

# 项目根目录：本文件在 clashDP/python/core/config.py，往上两级就是 clashDP/python
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 判断当前是"开发期"还是"打包后"
#   打包成 .deb 安装后，我们会把数据放到 /opt/clashDP，
#   并通过环境变量 CLASHDP_PACKAGED=1 来标记，程序据此切换路径。
IS_PACKAGED = os.environ.get("CLASHDP_PACKAGED", "") == "1"


def get_mihomo_dir():
    """返回"包含 mihomo 二进制"的目录（geoip.dat 等也放这里）。"""
    if IS_PACKAGED:
        return "/opt/clashDP"                       # 打包后：安装目录
    return os.path.join(PROJECT_ROOT, "data", "mihomo")  # 开发期：项目里的 data/mihomo


def get_mihomo_binary():
    """返回 mihomo 可执行文件的完整路径。"""
    return os.path.join(get_mihomo_dir(), "mihomo")


def get_user_config_dir():
    """
    返回用户配置目录（遵循 XDG 规范：~/.config/clashDP）。
    开发期用 clashDP-dev 子目录，避免污染你真实的配置。
    """
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    sub = "clashDP" if IS_PACKAGED else "clashDP-dev"
    return os.path.join(base, sub)


def get_config_file():
    """返回 config.yaml 的完整路径（mihomo 启动时读这个）。"""
    return os.path.join(get_user_config_dir(), "config.yaml")


def get_geoip_files():
    """返回地理库文件（geoip.dat / geosite.dat）所在目录。"""
    return get_mihomo_dir()


def read_secret():
    """
    从 config.yaml 读出控制口密钥（没密钥就连不上内核）。
    M4/M6 等多个模块都要用，统一放这里避免各写一遍。
    """
    import yaml
    p = get_config_file()
    if os.path.isfile(p):
        with open(p, "r", encoding="utf-8") as f:
            d = yaml.safe_load(f)
        if d and d.get("secret"):
            return d["secret"]
    raise RuntimeError(
        "读不到 secret：请先在『代理』页点『启动内核』生成 config.yaml")


# 用户偏好设置文件（JSON）：保存界面语言、主题等。
SETTINGS_FILE = os.path.join(get_user_config_dir(), "settings.json")

# 默认设置
DEFAULT_SETTINGS = {
    "language": "zh",   # 界面语言：zh 中文 / en 英文
    "theme": "auto",    # 主题：auto 跟随系统
    "tun_enabled": False,  # TUN 模式（M8）：全局透明代理，默认关闭
    "secret": "",       # 控制口密钥（固化保存，避免每次重建配置都换密钥导致 401）
}


def load_settings():
    """读取用户设置；文件不存在或格式错误时返回默认设置。"""
    data = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data.update(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return data


def save_settings(data):
    """保存用户设置到 JSON 文件（自动创建目录）。"""
    os.makedirs(get_user_config_dir(), exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _save_secret_to_settings(secret):
    """把密钥记进 settings.json（已经一样就不重复写盘）。"""
    data = load_settings()
    if data.get("secret") != secret:
        data["secret"] = secret
        save_settings(data)


def get_or_create_secret():
    """
    返回一个"长期稳定"的控制口密钥，供生成配置时使用。
    优先级：
      1) 现有 config.yaml 里的 secret —— 最权威，因为运行中的内核加载的就是它
      2) settings.json 里记录过的 secret
      3) 都没有：新生成一个，并写进 settings.json 固化下来

    为什么必须稳定：以前 build_config() 每次都随机新生成密钥，
    一旦"配置被重建但内核没重启"，APP 就和服务端密钥对不上，所有接口报 401。
    """
    # 1) 现有配置文件里的（内核当前正在用这个）
    p = get_config_file()
    if os.path.isfile(p):
        try:
            import yaml
            with open(p, "r", encoding="utf-8") as f:
                d = yaml.safe_load(f)
            if isinstance(d, dict) and d.get("secret"):
                _save_secret_to_settings(d["secret"])
                return d["secret"]
        except Exception:
            pass

    # 2) 设置里存过的
    s = load_settings().get("secret")
    if s:
        return s

    # 3) 新生成并固化
    import secrets as _secrets
    s = _secrets.token_hex(16)
    _save_secret_to_settings(s)
    return s
