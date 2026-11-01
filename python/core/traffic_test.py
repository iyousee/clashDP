"""
traffic_test.py —— 流量监控(M6)自检
  1) 离线：验证 format_bytes 格式化、速率计算逻辑（mock 内核返回）
  2) 在线：若内核在运行，真实读一次 /connections 看累计流量与连接数

怎么跑（真机 deepin）：
  cd clashDP/python
  .venv/bin/python -m core.traffic_test
"""
import sys

from PySide6.QtCore import QCoreApplication, QObject, Signal

from core import traffic as tf


def test_format_bytes():
    print("[离线] 验证 format_bytes 字节格式化")
    cases = [(0, "0 B"), (512, "512 B"), (1023, "1023 B"),
             (1024, "1.0 KB"), (1536, "1.5 KB"),
             (1048576, "1.00 MB"), (1073741824, "1.00 GB")]
    for n, expect in cases:
        got = tf.format_bytes(n)
        assert got == expect, "format_bytes(%d)=%s 应为 %s" % (n, got, expect)
    print("    [通过] format_bytes 正常")


class _Collector(QObject):
    got = Signal()

    def __init__(self):
        super().__init__()
        self.last = None

    def on_updated(self, down_rate, up_rate, total_down, total_up, conns):
        self.last = (down_rate, up_rate, total_down, total_up, conns)


def _fake_mihomo(total_down, total_up, conns):
    """替换掉 config.read_secret 与 MihomoAPI，返回假数据。"""
    tf.config.read_secret = lambda: "fake-secret"
    tf.mihomo_api.MihomoAPI = lambda secret: _FakeApi(total_down, total_up, conns)


class _FakeApi:
    def __init__(self, down, up, conns):
        self._down, self._up, self._conns = down, up, conns

    def get_connections(self):
        return {"downloadTotal": self._down, "uploadTotal": self._up,
                "connections": self._conns}


def test_rate_calc():
    print("[离线] 验证两次轮询之间的速率计算")
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    mon = tf.TrafficMonitor()
    col = _Collector()
    mon.updated.connect(col.on_updated)

    # 第一次：累计 0
    _fake_mihomo(0, 0, [])
    mon._poll()
    # 模拟过了 1 秒，累计下载涨到 2048 字节、上传 1024 字节
    _fake_mihomo(2048, 1024, [{"id": "1", "metadata": {"host": "example.com",
                  "network": "tcp", "type": "HTTPS"}, "chains": ["🔰 节点选择", "香港节点"],
                  "download": 2048, "upload": 1024}])
    import time
    time.sleep(1.0)
    mon._poll()

    down_rate, up_rate, total_down, total_up, conns = col.last
    # 1 秒涨 2048 字节下载 → 速率约 2048 B/s
    assert abs(down_rate - 2048) < 200, "下载速率算错: %d" % down_rate
    assert abs(up_rate - 1024) < 200, "上传速率算错: %d" % up_rate
    assert total_down == 2048 and total_up == 1024, "累计值不对"
    assert len(conns) == 1, "连接数不对"
    print("    下载速率=%d B/s 上传速率=%d B/s 累计下=%d 上=%d 连接=%d"
          % (down_rate, up_rate, total_down, total_up, len(conns)))
    print("    [通过] 速率计算正常")


def online_test():
    print("[在线] 尝试连接真实内核（需先启动内核）")
    try:
        from core import config
        secret = config.read_secret()
        from core import mihomo_api
        api = mihomo_api.MihomoAPI(secret)
        data = api.get_connections()
    except Exception as e:
        print("    （内核未运行或连不上，跳过在线测试：%s）" % e)
        return
    total_down = data.get("downloadTotal", 0)
    total_up = data.get("uploadTotal", 0)
    conns = data.get("connections", [])
    print("    累计下载: %s  累计上传: %s" % (tf.format_bytes(total_down), tf.format_bytes(total_up)))
    print("    当前连接数: %d" % len(conns))
    for c in conns[:5]:
        m = c.get("metadata", {})
        chain = c.get("chains", [])
        print("      - %s  →  %s  (出口 %s)"
              % (m.get("host", m.get("destinationIP", "?")),
                 tf.format_bytes(c.get("download", 0)),
                 chain[-1] if chain else "?"))
    print("    [通过] 在线实读正常")


def main():
    print("======= M6 流量监控自检 =======")
    test_format_bytes()
    test_rate_calc()
    print()
    online_test()
    print("=============================")


if __name__ == "__main__":
    main()
