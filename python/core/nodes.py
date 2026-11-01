"""
nodes.py —— 节点 & 策略组管理（M4 模块）
作用：
  1. 从 mihomo 读取"节点列表"和"策略组列表"
  2. 测单个/批量节点延迟
  3. 切换策略组（把某个策略组选到指定节点）
大白话：这是"看节点、挑节点、测速度、切分组"的业务封装，界面(M5)直接调它。
"""
import os
import yaml
import concurrent.futures

from core import mihomo_api, config

# 测延迟用的检测地址（返回 204 即视为可达），超时时间（毫秒）
DELAY_TEST_URL = "https://www.gstatic.com/generate_204"
DELAY_TIMEOUT_MS = 5000

# mihomo 里这些 type 是"策略组"（可切换/自动挑选），其余都是真实节点。
# 注意坑：mihomo 的 /proxies 接口返回的 type 是「PascalCase + 无连字符」，
# 例如 Selector / URLTest / Fallback / LoadBalance / Relay（注意 URLTest、LoadBalance 没有"-"）。
# 所以我们统一「转小写 + 去掉连字符」再比较，这样无论内核返回哪种写法都能认出来。
_GROUP_TYPES = {"selector", "urltest", "fallback", "loadbalance", "relay"}


def _is_group(info):
    """判断某个 /proxies 条目是不是策略组（大小写/连字符都兼容）。"""
    t = (info.get("type") or "").lower().replace("-", "")
    return t in _GROUP_TYPES


def _read_secret():
    """从 config.yaml 读出控制口密钥（没密钥就连不上内核）。"""
    p = config.get_config_file()
    if os.path.isfile(p):
        with open(p, "r", encoding="utf-8") as f:
            d = yaml.safe_load(f)
        if d and d.get("secret"):
            return d["secret"]
    raise RuntimeError("读不到 secret：请先生成 config.yaml（跑过 M1/M3 即可）")


class NodeManager:
    """和内核对话，提供"节点/策略组"相关操作。"""

    def __init__(self, secret=None):
        if secret is None:
            secret = _read_secret()
        self.api = mihomo_api.MihomoAPI(secret)

    # ---------- 读取 ----------
    def list_groups(self):
        """
        返回策略组列表，每条：{name, type, now(当前选中), all(可选节点名)}
        策略组 = selector(手动选) / url-test(自动测速) / fallback(故障转移) 等
        """
        data = self.api.get_proxies()
        proxies = data.get("proxies", {})
        groups = []
        for name, info in proxies.items():
            if _is_group(info):
                groups.append({
                    "name": name,
                    "type": info.get("type"),
                    "now": info.get("now"),
                    "all": info.get("all", []),
                })
        return groups

    def list_nodes(self):
        """
        返回真实节点列表，每条：{name, type, delay(延迟,初始None)}
        真实节点 = 除去策略组以外的所有项（ss/vmess/trojan/socks5/http...）
        """
        data = self.api.get_proxies()
        proxies = data.get("proxies", {})
        nodes = []
        for name, info in proxies.items():
            if _is_group(info):
                continue  # 这是策略组，不是真实节点
            nodes.append({
                "name": name,
                "type": info.get("type"),
                "delay": None,
            })
        return nodes

    # ---------- 测速 ----------
    def test_delay(self, name, url=DELAY_TEST_URL, timeout=DELAY_TIMEOUT_MS):
        """
        测单个节点的延迟（毫秒）。测不通/超时返回 None。
        """
        try:
            r = self.api.get_proxy_delay(name, url=url, timeout=timeout)
            return r.get("delay")
        except Exception:
            return None

    def test_all_delays(self, names, max_workers=10):
        """
        并发批量测速，返回 {节点名: 延迟ms 或 None}。
        用多线程，避免某个慢节点卡住全部。
        """
        result = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            future_to_name = {ex.submit(self.test_delay, n): n for n in names}
            for fut in concurrent.futures.as_completed(future_to_name):
                n = future_to_name[fut]
                try:
                    result[n] = fut.result()
                except Exception:
                    result[n] = None
        return result

    # ---------- 切换 ----------
    def select(self, group, target):
        """把某个策略组切换到 target 节点。返回是否成功。"""
        return self.api.switch_proxy(group, target)

    def current_of(self, group):
        """返回某个策略组当前选中的节点名。"""
        for g in self.list_groups():
            if g["name"] == group:
                return g["now"]
        return None
