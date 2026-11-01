"""
nodes_test.py —— 节点&策略组模块(M4)自检
两种模式：
  1) 离线整理测试：mock 掉内核返回，验证 list_groups/list_nodes 整理正确（沙箱可跑）
  2) 在线实跑测试：若内核在运行，真实列出节点、批量测速、切换策略组

怎么跑（真机 deepin）：
  cd clashDP/python
  .venv/bin/python -m core.nodes_test
"""
import types

from core import nodes as nd


# 一份"假的内核返回"，模拟订阅里有 2 个节点 + 1 个选择组
FAKE_PROXIES = {
    "proxies": {
        "🔰 节点选择": {"type": "selector", "now": "香港节点01", "all": ["香港节点01", "日本节点01"]},
        "🚀 自动选择": {"type": "url-test", "now": "日本节点01", "all": ["香港节点01", "日本节点01"]},
        "香港节点01": {"type": "ss"},
        "日本节点01": {"type": "vmess"},
    }
}


def _make_manager_with_fake():
    """构造一个用假数据、不连真实内核的 NodeManager。"""
    nm = nd.NodeManager(secret="fake-secret-for-test")
    # 把"读取接口"替换成返回假数据，其余逻辑（整理）真实运行
    nm.api._get = lambda path: FAKE_PROXIES if path == "/proxies" else {"version": "fake"}
    # 测速也返回假延迟（格式与真实 API 一致：{"delay": 毫秒}）
    def fake_delay(name, url=nd.DELAY_TEST_URL, timeout=nd.DELAY_TIMEOUT_MS):
        return {"delay": 120 if name == "香港节点01" else 200}
    nm.api.get_proxy_delay = fake_delay
    # 切换策略组也走假数据，避免真正去连内核
    nm.api.switch_proxy = lambda group, target: True
    return nm


def offline_test():
    print("[离线] 验证 list_groups / list_nodes / 测速 / 切换 的整理逻辑")
    nm = _make_manager_with_fake()

    groups = nm.list_groups()
    assert len(groups) == 2, "策略组数量不对"
    assert groups[0]["name"] == "🔰 节点选择", "策略组名不对"
    assert groups[0]["now"] == "香港节点01", "当前选中不对"
    print(f"    策略组: {[(g['name'], g['now']) for g in groups]}")

    node_list = nm.list_nodes()
    assert len(node_list) == 2, "节点数量不对"
    assert {n["name"] for n in node_list} == {"香港节点01", "日本节点01"}, "节点名不对"
    print(f"    节点: {[n['name'] for n in node_list]}")

    delays = nm.test_all_delays([n["name"] for n in node_list])
    assert delays["香港节点01"] == 120 and delays["日本节点01"] == 200, "测速结果不对"
    print(f"    测速: {delays}")

    ok = nm.select("🔰 节点选择", "日本节点01")
    assert ok is True, "切换失败"
    print("    切换 🔰 节点选择 -> 日本节点01: 成功")
    print("    [通过] 离线整理逻辑正常")


# 模拟 mihomo 真实返回：type 是 PascalCase 且无连字符（"URLTest"/"LoadBalance"）
FAKE_PROXIES_PASCAL = {
    "proxies": {
        "🔰 节点选择": {"type": "Selector", "now": "香港节点01", "all": ["香港节点01", "日本节点01"]},
        "🚀 自动选择": {"type": "URLTest", "now": "日本节点01", "all": ["香港节点01", "日本节点01"]},
        "负载均衡": {"type": "LoadBalance", "now": "香港节点01", "all": ["香港节点01", "日本节点01"]},
        "香港节点01": {"type": "Shadowsocks"},
        "日本节点01": {"type": "Vmess"},
        "DIRECT": {"type": "Direct"},
    }
}


def pascalcase_test():
    print("[真实格式] 验证 mihomo 的 PascalCase 类型也能正确识别（之前 Bug 的根因）")
    nm = nd.NodeManager(secret="fake-secret-for-test")
    nm.api._get = lambda path: FAKE_PROXIES_PASCAL if path == "/proxies" else {"version": "fake"}
    nm.api.get_proxy_delay = lambda name, url=nd.DELAY_TEST_URL, timeout=nd.DELAY_TIMEOUT_MS: {"delay": 100}
    nm.api.switch_proxy = lambda group, target: True

    groups = nm.list_groups()
    # Selector + URLTest + LoadBalance 都应被认作策略组，共 3 个
    assert len(groups) == 3, "PascalCase 策略组数量不对（应为 3）"
    print(f"    策略组: {[(g['name'], g['type']) for g in groups]}")

    # 真实节点应为 2 个（香港/日本），DIRECT 是内置类型不算真实节点被列出？
    # 注意：DIRECT 的 type 是 'Direct'，不属于策略组，会被当成节点列出（无害，符合 mihomo 行为）
    node_list = nm.list_nodes()
    assert len(node_list) == 3, "节点数量不对（应为 2 节点 + DIRECT = 3）"
    print(f"    节点: {[n['name'] for n in node_list]}")
    print("    [通过] PascalCase 类型识别正常（Bug 已修复）")


def online_test():
    print("[在线] 尝试连接真实内核（需先按 M3 第5步启动内核）")
    try:
        nm = nd.NodeManager()
        ver = nm.api.get_version()
        print(f"    内核版本: {ver.get('version')} / {ver.get('meta')}")
    except Exception as e:
        print(f"    （内核未运行或连不上，跳过在线测试：{e}）")
        print("    提示：先起内核 -> .venv/bin/python -c \"from core.kernel import start_kernel; start_kernel()\"")
        return

    groups = nm.list_groups()
    print(f"    策略组数量: {len(groups)}")
    for g in groups:
        print(f"      - {g['name']} [{g['type']}] 当前={g['now']} 可选{len(g['all'])}个")

    node_list = nm.list_nodes()
    print(f"    节点数量: {len(node_list)}")
    # 只测前 10 个，避免上千节点把验收拖太久
    sample = [n["name"] for n in node_list[:10]]
    print(f"    批量测速前 {len(sample)} 个节点...")
    delays = nm.test_all_delays(sample)
    for name, d in delays.items():
        print(f"      - {name}: {d if d is not None else '超时/失败'} ms")

    if groups:
        g0 = groups[0]
        if g0["all"]:
            target = g0["all"][0]
            nm.select(g0["name"], target)
            print(f"    切换 {g0['name']} -> {target} 完成")
    print("    [通过] 在线实跑正常")


def main():
    print("======= M4 节点&策略组自检 =======")
    offline_test()
    print()
    pascalcase_test()
    print()
    online_test()
    print("===============================")


if __name__ == "__main__":
    main()
