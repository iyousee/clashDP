"""
subscription_test.py —— 订阅模块(M3)自检（无需联网）
验证四件事：
  1. 纯 YAML 订阅能解析、合并、生成配置
  2. base64 包裹的订阅也能解析
  3. 只有节点、没有策略组/规则的"裸订阅"也能自动补上兜底组与规则
  4. 带规则集(rule-providers)的订阅：规则集被完整保留，引用了不存在规则集/节点的规则被剔除
     （这一项对应真机上 "rule set [private] not found" 的启动失败问题）

怎么跑（真机 deepin）：
  cd clashDP/python
  .venv/bin/python -m core.subscription_test
"""
import os
import sys
import base64
import tempfile

from core import subscription as sub
from core import kernel


def _write_tmp_yaml(content, suffix=".yaml"):
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="subtest_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _use_tmp_config():
    """每个测试用例用独立临时配置目录，避免互相污染 subscriptions.json。"""
    tmp = tempfile.mkdtemp(prefix="clashdp_cfg_")
    os.environ["XDG_CONFIG_HOME"] = tmp
    return tmp


def _verify_config(cfg):
    """断言生成配置的关键字段正确。"""
    assert isinstance(cfg, dict), "配置必须是字典"
    assert cfg["mixed-port"] == kernel.MIXED_PORT, "端口不对"
    assert isinstance(cfg["proxies"], list) and len(cfg["proxies"]) > 0, "没有节点"
    assert isinstance(cfg["proxy-groups"], list), "策略组缺失"
    assert isinstance(cfg["rules"], list) and len(cfg["rules"]) > 0, "规则缺失"
    names = {g["name"] for g in cfg["proxy-groups"]}
    assert sub.NODE_SELECT_NAME in names, "缺少兜底节点选择组"
    assert sub.AUTO_SELECT_NAME in names, "缺少兜底自动选择组"
    assert any(str(r).startswith("MATCH") for r in cfg["rules"]), "缺少 MATCH 兜底规则"


def test_plain_yaml():
    print("[测试1] 纯 YAML 订阅（含节点+策略组+规则）")
    _use_tmp_config()
    content = """
proxies:
  - name: "香港节点01"
    type: ss
    server: hk1.example.com
    port: 8388
    cipher: aes-256-gcm
    password: "abc"
  - name: "日本节点01"
    type: ss
    server: jp1.example.com
    port: 8388
    cipher: aes-256-gcm
    password: "xyz"
proxy-groups:
  - name: "我的策略组"
    type: select
    proxies: ["香港节点01", "日本节点01"]
rules:
  - "DOMAIN-SUFFIX,google.com,我的策略组"
  - "MATCH,DIRECT"
"""
    path = _write_tmp_yaml(content)
    mgr = sub.SubscriptionManager()
    sid = mgr.add_local("测试订阅A", path)
    mgr.update_one(sid)
    cfg, dropped = sub.generate_config_dict(mgr)
    _verify_config(cfg)
    print(f"    节点数={len(cfg['proxies'])} 策略组={len(cfg['proxy-groups'])} 规则={len(cfg['rules'])}")
    print("    [通过] 纯 YAML 解析/合并正常")


def test_base64():
    print("[测试2] base64 包裹的订阅")
    raw = """
proxies:
  - name: "美国节点01"
    type: vmess
    server: us1.example.com
    port: 443
    uuid: "1111"
    alterId: 0
    cipher: auto
"""
    b64 = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    # 模拟"远程拉取"：直接把 b64 文本喂给解析函数
    proxies, groups, rules = sub.parse_subscription_content(b64)
    assert len(proxies) == 1 and proxies[0]["name"] == "美国节点01", "base64 解析失败"
    print("    [通过] base64 订阅解析正常")


def test_bare_proxies():
    print("[测试3] 只有节点、没有策略组/规则的裸订阅（验证自动兜底）")
    _use_tmp_config()
    content = """
proxies:
  - name: "节点A"
    type: ss
    server: a.example.com
    port: 1
    cipher: aes-256-gcm
    password: "1"
  - name: "节点B"
    type: ss
    server: b.example.com
    port: 2
    cipher: aes-256-gcm
    password: "2"
"""
    path = _write_tmp_yaml(content)
    mgr = sub.SubscriptionManager()
    sid = mgr.add_local("裸订阅B", path)
    mgr.update_one(sid)
    cfg, dropped = sub.generate_config_dict(mgr)
    _verify_config(cfg)
    # 裸订阅没有规则，应自动补上"国内域名直连 + MATCH 兜底"
    assert any(str(r).startswith("DOMAIN-SUFFIX,cn") for r in cfg["rules"]), "没补国内直连规则"
    # 有 geoip.dat 时才会补 GEOIP,CN（没有地理库硬加会让内核启动失败）
    has_geo = os.path.isfile(os.path.join(kernel.config.get_geoip_files(), "geoip.dat"))
    if has_geo:
        assert any(str(r).startswith("GEOIP,CN") for r in cfg["rules"]), "有地理库却没补国内 IP 直连"
    print(f"    自动生成策略组: {[g['name'] for g in cfg['proxy-groups']]}")
    print(f"    自动生成规则条数: {len(cfg['rules'])}")
    print("    [通过] 裸订阅自动兜底正常")


def test_rule_providers():
    """这一步专治真机报错：配置里有 RULE-SET 规则，却没有 rule-providers 定义。"""
    print("[测试4] 带规则集(rule-providers)的订阅 + 坏的 RULE-SET 规则")
    _use_tmp_config()
    content = """
proxies:
  - name: "香港节点01"
    type: ss
    server: hk1.example.com
    port: 8388
    cipher: aes-256-gcm
    password: "abc"
proxy-groups:
  - name: "我的策略组"
    type: select
    proxies: ["香港节点01", "已删除的节点"]
rule-providers:
  private:
    type: http
    behavior: domain
    format: mrs
    url: "https://example.com/private.mrs"
    path: "./ruleset/private.mrs"
    interval: 86400
  openai:
    type: http
    behavior: domain
    format: mrs
    url: "https://example.com/openai.mrs"
    path: "./ruleset/openai.mrs"
    interval: 86400
rules:
  - "RULE-SET,private,DIRECT"
  - "RULE-SET,openai,我的策略组"
  - "RULE-SET,不存在的规则集,DIRECT"
  - "DOMAIN-SUFFIX,google.com,不存在的策略组"
  - "MATCH,DIRECT"
"""
    path = _write_tmp_yaml(content)
    mgr = sub.SubscriptionManager()
    sid = mgr.add_local("规则集订阅", path)
    mgr.update_one(sid)
    cfg, dropped = sub.generate_config_dict(mgr)

    # 1) 规则集定义必须被完整带进配置
    rp = cfg.get("rule-providers") or {}
    assert set(rp.keys()) == {"private", "openai"}, f"规则集丢失: {list(rp.keys())}"
    # 2) 合法 RULE-SET 规则要保留
    rules = cfg["rules"]
    assert "RULE-SET,private,DIRECT" in rules, "合法规则被误删"
    assert "RULE-SET,openai,我的策略组" in rules, "合法规则被误删"
    # 3) 引用了不存在规则集/策略组的规则要被剔除
    assert not any(r.startswith("RULE-SET,不存在的规则集") for r in rules), "坏规则集规则没被剔除"
    assert not any("不存在的策略组" in r for r in rules), "坏落点规则没被剔除"
    # 4) 策略组里引用不存在的节点要被剔掉，组本身保留
    g = next(g for g in cfg["proxy-groups"] if g["name"] == "我的策略组")
    assert g["proxies"] == ["香港节点01"], f"组内坏节点没被剔除: {g['proxies']}"

    print(f"    规则集: {list(rp.keys())}")
    print(f"    被剔除的规则/成员: {len(dropped)} 条 -> {[d[0] for d in dropped]}")
    print("    [通过] 规则集保留 + 坏规则自动剔除")


def main():
    print("======= M3 订阅模块自检 =======")
    test_plain_yaml()
    test_base64()
    test_bare_proxies()
    test_rule_providers()
    print("==============================")
    print("全部通过 ✅")
    # 清理：移除测试产生的本地订阅记录（保留用户真实已有的订阅）
    # （仅当这些 id 是本次测试创建时才删，简单起见不自动删，提示用户）


if __name__ == "__main__":
    main()
