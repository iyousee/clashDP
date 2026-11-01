"""
kernel_log_test.py —— M7 日志增量读取自检（离线，不依赖真实内核）
覆盖：文件不存在 / 首次读 / 无新增 / 增量追加 / 文件被清空重写（内核重启）。
"""
import os
import tempfile
from core import kernel_log


def main():
    print("======= M7 日志增量读取自检 =======")
    d = tempfile.mkdtemp()
    p = os.path.join(d, "mihomo.log")

    tail = kernel_log.KernelLogTail(p)

    # 1) 文件还不存在
    assert tail.read_new() == [], "文件不存在应返回空列表"
    print("[通过] 文件不存在 -> 空列表")

    # 2) 首次写入 3 行
    with open(p, "w", encoding="utf-8") as f:
        f.write("INFO[1] a\nINFO[2] b\nWARN[3] c\n")
    got = tail.read_new()
    assert got == ["INFO[1] a", "INFO[2] b", "WARN[3] c"], got
    print("[通过] 首次读取 3 行")

    # 3) 没有新内容
    assert tail.read_new() == [], "无新增应返回空"
    print("[通过] 无新增 -> 空列表")

    # 4) 追加 2 行
    with open(p, "a", encoding="utf-8") as f:
        f.write("ERROR[4] d\nINFO[5] e\n")
    got = tail.read_new()
    assert got == ["ERROR[4] d", "INFO[5] e"], got
    print("[通过] 增量读取 2 行")

    # 5) 文件被清空重写（模拟内核重启）—— 应自动从头读
    with open(p, "w", encoding="utf-8") as f:
        f.write("INFO[9] restart\n")
    got = tail.read_new()
    assert got == ["INFO[9] restart"], got
    print("[通过] 文件清空重写后自动从头读")

    print("=================================")


if __name__ == "__main__":
    main()
