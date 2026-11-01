"""
subscription.py —— 订阅管理（M3 模块）
作用：
  1. 添加订阅（远程链接 or 本地配置文件）
  2. 拉取并解析订阅内容（兼容纯 YAML 和 base64 包裹的 YAML）
  3. 把多个订阅的节点/策略组/规则合并，生成 mihomo 的 config.yaml
  4. 一键更新 + 定时自动更新（后台线程）

大白话：机场给你一个"订阅链接"，点一下就能把里面成百上千个节点拉下来，
        我们再把它们和规则拼成 clash 能用的配置文件。
"""
import os
import re
import base64
import json
import time
import uuid
import threading
from datetime import datetime, timezone

import requests
import yaml

from core import config
from core import kernel


# ---------------------------------------------------------------------------
# 第一部分：订阅内容的解析（不依赖网络，纯文本 -> 结构化数据）
# ---------------------------------------------------------------------------

def _looks_like_base64(text):
    """判断一段文本是否像 base64 编码（机场常用 base64 包裹 yaml）。"""
    s = text.strip()
    if not s or len(s) % 4 != 0:
        return False
    # base64 字符集：字母、数字、+、/、=（补位）
    return bool(re.fullmatch(r"[A-Za-z0-9+/=]+", s))


def _try_b64_decode(text):
    """
    如果 text 是 base64 包裹的 yaml，返回解码后的 yaml 文本；否则返回 None。
    只有"解码后确实是 clash 配置"才采用，避免误判。
    """
    if not _looks_like_base64(text):
        return None
    try:
        raw = base64.b64decode(text, validate=True)
        decoded = raw.decode("utf-8")
        data = yaml.safe_load(decoded)
        # 解码结果里有 proxies 或 proxy-groups 才认定它是订阅
        if isinstance(data, dict) and ("proxies" in data or "proxy-groups" in data):
            return decoded
    except Exception:
        pass
    return None


def parse_subscription(text):
    """
    把订阅原始文本解析成字典（这是最完整的解析，保留全部关键段）。
    兼容两种格式：
      A. 直接就是 yaml（顶层含 proxies / proxy-groups / rules）
      B. 用 base64 编码过的 yaml

    返回字典，键说明：
      proxies        —— 节点列表
      groups         —— 策略组列表（对应 yaml 里的 proxy-groups）
      rules          —— 规则列表
      rule-providers —— 规则集提供者（订阅里的规则常写成 RULE-SET,xxx，必须靠它才能生效）
      proxy-providers—— 节点提供者（部分机场用"远程节点集合"，这里原样保留）
    """
    text = (text or "").strip()
    decoded = _try_b64_decode(text)
    if decoded is not None:
        text = decoded

    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("订阅内容不是合法的 clash 配置（缺少 proxies/proxy-groups）")

    return {
        "proxies": data.get("proxies") or [],
        "groups": data.get("proxy-groups") or [],
        "rules": data.get("rules") or [],
        "rule-providers": data.get("rule-providers") or {},
        "proxy-providers": data.get("proxy-providers") or {},
    }


def parse_subscription_content(text):
    """
    旧接口（保留兼容）：只取 (proxies, proxy_groups, rules) 三样。
    新代码建议直接用 parse_subscription()，因为它还带规则集定义。
    """
    d = parse_subscription(text)
    return d["proxies"], d["groups"], d["rules"]


# ---------------------------------------------------------------------------
# 第二部分：网络拉取 & 本地读取
# ---------------------------------------------------------------------------

def fetch_remote(url, ua="clashDP", timeout=20):
    """通过 HTTP 拉取远程订阅内容（文本）。"""
    headers = {"User-Agent": ua}
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.text


def fetch_local(path):
    """读取本地订阅文件（其实就是个 yaml 配置）。"""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_subscription_source(sub):
    """
    根据订阅记录(sub)取出它的原始文本内容。
    sub["type"] == "remote" -> 联网拉取
    sub["type"] == "local"  -> 读本地文件
    """
    if sub["type"] == "remote":
        return fetch_remote(sub["url"], ua=sub.get("ua", "clashDP"))
    else:
        return fetch_local(sub["path"])


# ---------------------------------------------------------------------------
# 第三部分：合并多个订阅（去重 + 兜底策略组/规则）
# ---------------------------------------------------------------------------

# 兜底策略组/规则使用的固定中文名，界面(M4)和 MATCH 兜底都要引用它
NODE_SELECT_NAME = "🔰 节点选择"
AUTO_SELECT_NAME = "🚀 自动选择"

# 规则里可以直接写、不需要对应节点的"内置目标"
BUILTIN_TARGETS = {"DIRECT", "REJECT", "REJECT-DROP", "PASS", "COMPATIBLE"}


def _sanitize_groups(groups, proxy_names):
    """
    清洗策略组：把组里引用了"不存在的节点/组"的成员剔掉。
    为什么要做：订阅里的组偶尔会引用某个已被机场删掉的节点，
    内核遇到这种"引用了不存在的名字"会直接拒绝启动。
    成员被剔空的组也一并丢弃（空组同样会让内核报错）。
    """
    known = set(proxy_names) | {g.get("name") for g in groups if g.get("name")} | BUILTIN_TARGETS
    clean = []
    for g in groups:
        if not isinstance(g, dict) or not g.get("name"):
            continue
        # 用 proxy-provider 的组（有 use 字段）不处理成员，原样保留
        if g.get("use"):
            clean.append(g)
            continue
        members = [m for m in (g.get("proxies") or []) if m in known]
        if not members:
            continue
        g2 = dict(g)
        g2["proxies"] = members
        clean.append(g2)
    return clean


def _rule_fields(rule):
    """把一条规则按逗号切开，并去掉结尾的 no-resolve / src 修饰词。"""
    segs = [s.strip() for s in str(rule).split(",")]
    tail = []
    while segs and segs[-1].lower() in ("no-resolve", "src"):
        tail.insert(0, segs.pop())
    return segs, tail


def sanitize_rules(rules, provider_names, proxy_names, group_names, geo_ok=True):
    """
    清洗规则：把内核"看不懂 / 用不了"的规则筛掉，保证配置一定能启动。
    会被剔除的三类：
      1. RULE-SET,名字 —— 但订阅里没有定义这个规则集（就是这次启动失败的原因）
      2. GEOIP / GEOSITE —— 但本地缺 geoip.dat / geosite.dat 地理库
      3. 规则的落点（DIRECT/策略组名）不存在
    返回 (保留的规则, 被剔除的[(规则, 原因)])，剔除原因会显示给用户。
    """
    known_targets = set(proxy_names) | set(group_names) | BUILTIN_TARGETS
    kept, dropped = [], []
    for r in rules or []:
        segs, tail = _rule_fields(r)
        if not segs:
            continue
        kind = segs[0].upper()

        # 1) 规则集必须先有定义
        if kind == "RULE-SET":
            name = segs[1] if len(segs) > 1 else ""
            if name not in provider_names:
                dropped.append((str(r), f"规则集 [{name}] 未定义"))
                continue

        # 2) 地理库规则需要本地有 .dat 文件
        if kind in ("GEOIP", "GEOSITE") and not geo_ok:
            dropped.append((str(r), "缺少地理库文件"))
            continue

        # 3) 落点必须存在（MATCH 只有一个目标，单独处理）
        target = segs[1] if kind == "MATCH" and len(segs) > 1 else (segs[-1] if len(segs) > 2 else "")
        if target and target not in known_targets:
            dropped.append((str(r), f"落点 [{target}] 不存在"))
            continue

        kept.append(str(r))
    return kept, dropped


def merge_subscriptions(proxies_list, groups_list, rules_list,
                        rule_providers_list=None, proxy_providers_list=None,
                        geo_ok=True):
    """
    把多个订阅解析出来的内容合并成一份。
    规则：
      - 节点按名字去重（同名后者覆盖前者）
      - 策略组按名字去重
      - 规则集(rule-providers)按名字合并——没有它，RULE-SET 规则全部失效
      - 若没有任何"节点选择"类 select 组，自动建一个兜底选择组（含所有节点）
      - 永远补一个"自动测速"组（url-test，自动挑最快节点）
      - 规则：取第一个订阅的规则；若没有 MATCH 收尾，补国内直连 + 兜底走代理
      - 最后统一清洗：删掉引用了不存在节点/规则集的条目，避免内核启动失败
    """
    # ---- 节点去重 ----
    proxy_map = {}
    for p in proxies_list:
        if isinstance(p, dict) and p.get("name"):
            proxy_map[p["name"]] = p
    proxies = list(proxy_map.values())
    all_names = [p["name"] for p in proxies]

    # ---- 策略组去重 ----
    group_map = {}
    for g in groups_list:
        if isinstance(g, dict) and g.get("name"):
            group_map[g["name"]] = g

    # ---- 规则集合并（多个订阅同名则后者覆盖）----
    rule_providers = {}
    for rp in (rule_providers_list or []):
        if isinstance(rp, dict):
            rule_providers.update(rp)

    # ---- 节点提供者合并 ----
    proxy_providers = {}
    for pp in (proxy_providers_list or []):
        if isinstance(pp, dict):
            proxy_providers.update(pp)

    # 兜底组只在"确实有节点"时才加，否则空组会让内核报错
    if all_names:
        group_map[NODE_SELECT_NAME] = {
            "name": NODE_SELECT_NAME,
            "type": "select",
            "proxies": all_names,
        }
        group_map[AUTO_SELECT_NAME] = {
            "name": AUTO_SELECT_NAME,
            "type": "url-test",
            "proxies": all_names,
            "url": "https://www.gstatic.com/generate_204",
            "interval": 300,
        }
    groups = _sanitize_groups(list(group_map.values()), all_names)

    # ---- 规则兜底 ----
    rules = list(rules_list or [])
    has_match = any(str(r).startswith("MATCH") for r in rules)
    if not has_match:
        # 国内域名直连，其余兜底走"节点选择"
        # GEOIP,CN 只有本地有 geoip.dat 时才加，否则内核会因为找不到地理库而拒绝启动
        if geo_ok:
            rules = rules + ["DOMAIN-SUFFIX,cn,DIRECT", "GEOIP,CN,DIRECT",
                             f"MATCH,{NODE_SELECT_NAME}"]
        else:
            rules = rules + ["DOMAIN-SUFFIX,cn,DIRECT", f"MATCH,{NODE_SELECT_NAME}"]

    # ---- 统一清洗（这一步是这次"启动失败"的根治手段）----
    group_names = [g["name"] for g in groups]
    rules, dropped = sanitize_rules(
        rules, set(rule_providers.keys()), all_names, group_names, geo_ok=geo_ok)

    return proxies, groups, rules, rule_providers, proxy_providers, dropped


# ---------------------------------------------------------------------------
# 第四部分：生成最终 config.yaml
# ---------------------------------------------------------------------------

def _read_existing_secret():
    """
    复用"稳定密钥"：优先现有 config.yaml，其次 settings.json 里记录的，最后才新生成并固化。
    统一走 config.get_or_create_secret，避免订阅重建配置时换掉密钥，导致 APP 与内核 401。
    """
    return config.get_or_create_secret()


def _geo_available():
    """本地是否有 geoip.dat / geosite.dat（没有的话 GEOIP/GEOSITE 规则必须剔除）。"""
    d = config.get_geoip_files()
    return (os.path.isfile(os.path.join(d, "geoip.dat"))
            or os.path.isfile(os.path.join(d, "GeoIP.dat")))


def generate_config_dict(manager):
    """
    根据当前启用的订阅，生成完整的 mihomo 配置字典。
    骨架(dns/tun/控制口/端口)沿用 kernel.build_config，
    再替换 proxies / proxy-groups / rule-providers / rules 这些段。
    返回 (配置字典, 警告列表)；警告列表里是被自动剔除的规则及原因。
    """
    subs = manager.list_enabled()
    all_proxies, all_groups, first_rules = [], [], []
    all_rule_providers, all_proxy_providers = [], []

    for sub in subs:
        parsed = sub.get("parsed")
        if not parsed:
            continue
        # 旧版本缓存可能没存规则集定义；如果保存过订阅原始文本，就现场重新解析一次补全
        if not parsed.get("rule-providers") and sub.get("raw"):
            try:
                reparsed = parse_subscription(sub["raw"])
                if reparsed.get("rule-providers"):
                    parsed = dict(parsed)
                    parsed["rule-providers"] = reparsed["rule-providers"]
                    parsed["proxy-providers"] = reparsed.get("proxy-providers") or {}
            except Exception:
                pass
        all_proxies += parsed.get("proxies", [])
        all_groups += parsed.get("groups", [])
        # 规则集是"全局共享"的，所有订阅的都合并进来
        if parsed.get("rule-providers"):
            all_rule_providers.append(parsed["rule-providers"])
        if parsed.get("proxy-providers"):
            all_proxy_providers.append(parsed["proxy-providers"])
        # 规则取第一个有规则订阅的（避免重复叠加）
        if not first_rules and parsed.get("rules"):
            first_rules = parsed.get("rules", [])

    proxies, groups, rules, rule_providers, proxy_providers, dropped = merge_subscriptions(
        all_proxies, all_groups, first_rules,
        all_rule_providers, all_proxy_providers,
        geo_ok=_geo_available())

    # 订阅规则里用了 RULE-SET，但缓存里没有规则集定义：
    # 多半是旧版本缓存的订阅（那时没保存 rule-providers），提示用户重新拉取一次
    if not rule_providers and any(str(r).upper().startswith("RULE-SET") for r in first_rules):
        dropped.append(("整份订阅", "缓存里缺少规则集定义，请点\"更新全部\"重新拉取"))

    cfg = kernel.build_config(secret=_read_existing_secret())
    cfg["proxies"] = proxies
    cfg["proxy-groups"] = groups
    cfg["rules"] = rules
    # 规则集定义必须写进配置，否则 RULE-SET 规则全部失效、内核拒绝启动
    if rule_providers:
        cfg["rule-providers"] = rule_providers
    if proxy_providers:
        cfg["proxy-providers"] = proxy_providers
    return cfg, dropped


def apply_subscriptions(validate=True):
    """
    真机"一键更新/应用"时调用：读取订阅 -> 生成 -> 校验 -> 写盘。
    validate=True 时：先写到临时文件用 `mihomo -t` 试跑，
      校验不过就"降级"（把 RULE-SET / GEOIP 等容易出问题的规则全去掉）再校验一次；
      仍然不过就报错且不覆盖原配置——避免把能用的配置搞坏。
    返回统计信息字典（给界面/日志用）。
    """
    manager = SubscriptionManager()
    cfg, dropped = generate_config_dict(manager)

    warnings = [f"{r}（{why}）" for r, why in dropped]

    if validate and kernel.find_mihomo():
        ok, log = kernel.verify_config_dict(cfg)
        if not ok:
            # 降级重试：去掉所有 RULE-SET / GEOIP / GEOSITE 规则
            basic = [r for r in cfg["rules"]
                     if not str(r).split(",")[0].upper() in ("RULE-SET", "GEOIP", "GEOSITE")]
            if not any(str(r).startswith("MATCH") for r in basic):
                basic.append(f"MATCH,{NODE_SELECT_NAME}")
            cfg["rules"] = basic
            ok2, log2 = kernel.verify_config_dict(cfg)
            if not ok2:
                raise RuntimeError(
                    "生成的配置未通过内核校验，已保留原配置。\n内核提示：\n" + (log2 or log))
            warnings.append("规则集/地理库规则校验未通过，已自动降级为基础规则")

    path = kernel.write_config(cfg)
    return {
        "config_path": path,
        "proxy_count": len(cfg["proxies"]),
        "group_count": len(cfg["proxy-groups"]),
        "rule_count": len(cfg["rules"]),
        "provider_count": len(cfg.get("rule-providers") or {}),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# 第五部分：订阅管理器（增删改查 + 持久化）
# ---------------------------------------------------------------------------

class SubscriptionManager:
    """管理用户的订阅列表，保存到 <配置目录>/subscriptions.json。"""

    def __init__(self):
        self.dir = config.get_user_config_dir()
        self.file = os.path.join(self.dir, "subscriptions.json")
        self.data = self._load()

    def _load(self):
        try:
            with open(self.file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"subscriptions": []}

    def save(self):
        os.makedirs(self.dir, exist_ok=True)
        with open(self.file, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    # ---- 新增 ----
    def add_remote(self, name, url, interval=24, ua="clashDP"):
        """添加一个远程订阅链接。interval=自动更新间隔(小时)，0=不自动。"""
        sub = {
            "id": uuid.uuid4().hex[:12],
            "name": name,
            "type": "remote",
            "url": url,
            "ua": ua,
            "interval": interval,
            "enabled": True,
            "updated_at": None,
            "node_count": 0,
            "parsed": None,
        }
        self.data["subscriptions"].append(sub)
        self.save()
        return sub["id"]

    def add_local(self, name, path):
        """添加一个本地配置文件（path 是 yaml 文件绝对路径）。"""
        sub = {
            "id": uuid.uuid4().hex[:12],
            "name": name,
            "type": "local",
            "path": path,
            "interval": 0,           # 本地文件不自动更新
            "enabled": True,
            "updated_at": None,
            "node_count": 0,
            "parsed": None,
        }
        self.data["subscriptions"].append(sub)
        self.save()
        return sub["id"]

    # ---- 删除 / 开关 ----
    def remove(self, sid):
        self.data["subscriptions"] = [s for s in self.data["subscriptions"] if s["id"] != sid]
        self.save()

    def set_enabled(self, sid, enabled):
        for s in self.data["subscriptions"]:
            if s["id"] == sid:
                s["enabled"] = enabled
                self.save()
                return True
        return False

    # ---- 查询 ----
    def list_all(self):
        return self.data["subscriptions"]

    def list_enabled(self):
        return [s for s in self.data["subscriptions"] if s.get("enabled")]

    def get(self, sid):
        for s in self.data["subscriptions"]:
            if s["id"] == sid:
                return s
        return None

    # ---- 更新 ----
    def update_one(self, sid):
        """拉取单个订阅并解析，把结果缓存进 parsed 字段（含规则集定义）。"""
        sub = self.get(sid)
        if not sub or not sub.get("enabled"):
            return None
        text = load_subscription_source(sub)
        parsed = parse_subscription(text)
        # 只存解析结果里需要的字段，避免把整份原始配置塞进 json
        sub["parsed"] = {
            "proxies": parsed["proxies"],
            "groups": parsed["groups"],
            "rules": parsed["rules"],
            "rule-providers": parsed["rule-providers"],
            "proxy-providers": parsed["proxy-providers"],
        }
        sub["node_count"] = len(parsed["proxies"])
        # 顺手存一份原始文本：以后即使机场暂时连不上，也能从缓存重新生成完整配置
        if len(text) <= 2 * 1024 * 1024:      # 超过 2MB 就不存了，避免 json 太大
            sub["raw"] = text
        sub["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.save()
        return sub

    def update_all(self):
        results = []
        for s in self.list_enabled():
            try:
                self.update_one(s["id"])
                results.append((s["name"], "ok"))
            except Exception as e:
                results.append((s["name"], f"失败: {e}"))
        return results

    def check_and_update_due(self):
        """检查哪些订阅到了自动更新时间，到期就刷新（供定时线程调用）。"""
        now = time.time()
        for s in self.list_enabled():
            interval = s.get("interval", 0) or 0
            if interval <= 0:
                continue
            last = s.get("updated_at")
            if not last:
                self.update_one(s["id"])
                continue
            try:
                last_ts = datetime.fromisoformat(last).timestamp()
            except Exception:
                last_ts = 0
            if now - last_ts >= interval * 3600:
                self.update_one(s["id"])


# ---------------------------------------------------------------------------
# 第六部分：定时自动更新（后台线程，M5 界面启动/停止它）
# ---------------------------------------------------------------------------

class UpdateScheduler:
    """每隔一段时间检查订阅是否到期并自动更新。"""

    def __init__(self, manager, check_interval=3600):
        self.manager = manager
        self.check_interval = check_interval  # 多久扫一次（秒）
        self._timer = None
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        self._tick()

    def _tick(self):
        if not self._running:
            return
        try:
            self.manager.check_and_update_due()
        except Exception:
            pass  # 后台任务出错不应打断主程序
        self._timer = threading.Timer(self.check_interval, self._tick)
        self._timer.daemon = True  # 主程序退出时它跟着退出
        self._timer.start()

    def stop(self):
        self._running = False
        if self._timer:
            self._timer.cancel()
            self._timer = None


# 方便其它模块直接拿到兜底组名
__all__ = [
    "SubscriptionManager", "UpdateScheduler",
    "NODE_SELECT_NAME", "AUTO_SELECT_NAME",
    "parse_subscription", "parse_subscription_content",
    "generate_config_dict", "apply_subscriptions",
    "merge_subscriptions", "sanitize_rules",
]
