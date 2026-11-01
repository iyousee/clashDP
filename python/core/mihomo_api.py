"""
mihomo_api.py —— 封装 mihomo 的本地控制接口（REST）
说明：mihomo 启动后会在 127.0.0.1:9090 提供一个控制接口，所有请求都要带密钥。
      本模块是后续 M4(节点/测速/切策略组)、M6(流量)、M7(日志) 的统一底座。
"""
import requests


class SecretError(RuntimeError):
    """
    控制口密钥不一致（HTTP 401）。
    典型场景：配置文件被重建换了 secret，但内核还是用旧 secret 在跑。
    """
    pass


class MihomoAPI:
    """mihomo 控制接口的轻量封装。"""

    def __init__(self, secret, host="127.0.0.1", port=9090, timeout=5):
        self.base = f"http://{host}:{port}"
        # 密钥通过 HTTP 头 Authorization: Bearer <secret> 发送
        self.headers = {"Authorization": f"Bearer {secret}"}
        self.timeout = timeout

    # ---------- 内部通用方法 ----------
    @staticmethod
    def _check(r):
        """统一检查响应：401 单独翻译成"密钥不一致"的可操作提示。"""
        if r.status_code == 401:
            raise SecretError(
                "控制口密钥不一致（401）：APP 读到的 secret 与运行中的内核不同。\n"
                "解决办法：到「代理」页点「停止内核」，再点「启动内核」重新同步。\n"
                "若停止无效（内核不是本程序启动的），可在终端执行：pkill -f mihomo"
            )
        r.raise_for_status()

    def _get(self, path):
        r = requests.get(self.base + path, headers=self.headers, timeout=self.timeout)
        self._check(r)
        return r.json()

    def _patch(self, path, data):
        r = requests.patch(self.base + path, headers=self.headers,
                           json=data, timeout=self.timeout)
        self._check(r)
        return r.json() if r.content else {}

    # ---------- M2 用：读取/切换路由模式 ----------
    def get_version(self):
        """获取内核版本信息。"""
        return self._get("/version")

    def get_configs(self):
        """读取当前配置（含 mode）。"""
        return self._get("/configs")

    def set_mode(self, mode):
        """
        切换路由模式。mode 取值：
          "rule"   规则模式（按规则分流，最常用）
          "global" 全局模式（全部走代理）
          "direct" 直连模式（全部不走代理）
        """
        return self._patch("/configs", {"mode": mode})

    # ---------- 以下供 M4/M6/M7 使用（先写好接口） ----------
    def get_proxies(self):
        """获取所有节点、策略组及当前选中。"""
        return self._get("/proxies")

    def get_connections(self):
        """
        获取当前所有连接 + 累计上下行流量。
        返回 /connections 完整 JSON，关键字段：
          downloadTotal / uploadTotal：自内核启动以来的累计字节数
          connections：连接列表（含 metadata 域名/协议、chains 出口节点、upload/download）
        M6 流量监控用这个接口轮询，无需 WebSocket。
        """
        return self._get("/connections")

    def get_proxy_delay(self, name, url="https://www.gstatic.com/generate_204", timeout=5000):
        """测某个节点的延迟（毫秒）。"""
        return self._get(f"/proxies/{name}/delay?url={url}&timeout={timeout}")

    def switch_proxy(self, name, target):
        """把某个策略组/节点切换到 target。"""
        r = requests.put(self.base + f"/proxies/{name}", headers=self.headers,
                         json={"name": target}, timeout=self.timeout)
        self._check(r)
        return True
