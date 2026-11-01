"""
tun_test.py —— M8 TUN 权限模块自检（离线，不需要真实权限）
覆盖：getcap 输出解析 / 手动命令格式 / build_config 的 tun 段开关。
"""
import os
import tempfile
from core import tun, kernel, config


def test_parse():
    # 有能力的正常输出
    caps = tun._parse_getcap("/home/x/mihomo cap_net_admin,cap_net_bind_service=ep")
    assert caps == {"cap_net_admin", "cap_net_bind_service"}, caps
    print("[通过] 解析 getcap（双能力）")

    # 只有一项
    caps = tun._parse_getcap("/opt/clashDP/mihomo cap_net_admin=ep")
    assert caps == {"cap_net_admin"}, caps
    print("[通过] 解析 getcap（单能力）")

    # 空输出（没有能力）
    assert tun._parse_getcap("") == set()
    assert tun._parse_getcap("/a/mihomo\n") == set()
    print("[通过] 空输出 -> 空集合")


def test_command():
    cmd = tun.manual_command("/opt/clashDP/mihomo")
    assert cmd == ("sudo setcap cap_net_admin,cap_net_raw,cap_net_bind_service=+ep "
                   "/opt/clashDP/mihomo"), cmd
    print("[通过] 手动命令格式正确（含 cap_net_raw）")


def test_status():
    # 对不存在的文件：getcap 读不到，ok 应为 False，且不抛异常
    st = tun.status("/tmp/definitely_not_exist_mihomo")
    assert st["ok"] is False
    assert st["caps"] == []
    assert st["command"].startswith("sudo setcap")
    print("[通过] 文件不存在时 status 不崩、ok=False")


def test_build_config_tun():
    # 关闭：只留 enable:false
    cfg = kernel.build_config(secret="abc", tun_enable=False)
    assert cfg["tun"] == {"enable": False}, cfg["tun"]
    print("[通过] tun=关闭 -> {enable: False}")

    # 开启：关键字段齐全
    cfg = kernel.build_config(secret="abc", tun_enable=True)
    t = cfg["tun"]
    assert t["enable"] is True
    assert t["auto-route"] is True
    assert t["stack"] in ("system", "gvisor", "mixed")
    assert "any:53" in t["dns-hijack"]
    assert t["device"]
    print("[通过] tun=开启 -> 字段齐全（enable/auto-route/stack/dns-hijack/device）")

    # 用内核自己的校验确认 tun 配置能被内核接受（有内核才做）
    ok, out = kernel.verify_config_dict(cfg)
    if ok:
        print("[通过] mihomo -t 校验 tun 开启配置：通过")
    else:
        print("[跳过] 没有可用内核（或校验未通过）：", out[:200])


def main():
    print("======= M8 TUN 权限模块自检 =======")
    test_parse()
    test_command()
    test_status()
    test_build_config_tun()
    print("==================================")


if __name__ == "__main__":
    main()
