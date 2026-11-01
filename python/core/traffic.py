"""
traffic.py —— 流量监控（M6 模块）
作用：
  1. 实时上下行速度（轮询 mihomo /connections，用累计值算速率）
  2. 累计下载/上传流量
  3. 当前连接列表（域名/出口节点/协议/上下行；Linux 无 TUN 时拿不到进程名）
大白话：这一页让你看见"现在走了多少流量、每条连接去了哪、走的哪个节点"。
注意：用 REST 轮询而不是 WebSocket，简单且够用（1 秒刷新一次）。
"""
from PySide6.QtCore import QObject, QTimer, Signal

from core import mihomo_api, config

# 轮询间隔（毫秒）：1 秒一次，速度精度足够，也不给内核添负担
POLL_INTERVAL_MS = 1000


class TrafficMonitor(QObject):
    """
    流量监控器。挂在 Qt 事件循环里，用 QTimer 定时拉 /connections。
       updated(down_rate, up_rate, total_down, total_up, connections)
           down_rate/up_rate：瞬时速率（字节/秒）
           total_down/total_up：累计字节（直接来自内核，最准）
           connections：当前连接列表（原始字典）
       error(msg)：读取出错（多半是内核没跑或密钥不对）
    """

    updated = Signal(int, int, int, int, list)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)
        # 上一次轮询的累计值和时间戳，用来算速率
        self._prev_down = None
        self._prev_up = None
        self._prev_ts = None

    def start(self):
        """开始轮询（只负责起定时器，密钥在每次轮询时现读，避免内核重启后密钥失效）。"""
        if not self._timer.isActive():
            self._prev_down = self._prev_up = self._prev_ts = None
            self._timer.start()

    def stop(self):
        """停止轮询。"""
        self._timer.stop()

    def _poll(self):
        # 每次都现读密钥 + 新建 API 对象：内核若被重启并重新生成了 config（新密钥），
        # 这里能立刻跟上，不会拿旧密钥一直 401。
        try:
            secret = config.read_secret()
            api = mihomo_api.MihomoAPI(secret)
            data = api.get_connections()
        except Exception as e:
            self.error.emit(str(e))
            self._timer.stop()   # 出错就停，避免每秒刷错误
            return

        total_down = int(data.get("downloadTotal", 0) or 0)
        total_up = int(data.get("uploadTotal", 0) or 0)
        conns = data.get("connections", []) or []

        # 用"当前累计 - 上次累计"除以经过的秒数 = 瞬时速率
        down_rate = up_rate = 0
        now = _now_ms()
        if self._prev_ts is not None:
            dt = (now - self._prev_ts) / 1000.0
            if dt > 0:
                down_rate = max(0, int((total_down - self._prev_down) / dt))
                up_rate = max(0, int((total_up - self._prev_up) / dt))
        self._prev_down, self._prev_up, self._prev_ts = total_down, total_up, now

        self.updated.emit(down_rate, up_rate, total_down, total_up, conns)


def _now_ms():
    """当前毫秒时间戳（跨平台）。"""
    from PySide6.QtCore import QDateTime
    return QDateTime.currentMSecsSinceEpoch()


def format_bytes(n):
    """把字节数转成人类可读字符串：123 B / 1.2 KB / 3.45 MB / 6.78 GB。"""
    n = int(n or 0)
    if n < 1024:
        return "%d B" % n
    elif n < 1024 ** 2:
        return "%.1f KB" % (n / 1024.0)
    elif n < 1024 ** 3:
        return "%.2f MB" % (n / 1024.0 ** 2)
    else:
        return "%.2f GB" % (n / 1024.0 ** 3)
