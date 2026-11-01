"""
kernel_log.py —— 内核日志增量读取（M7 模块）
作用：像 `tail -f` 一样，只读取 mihomo 日志文件"新增的部分"，供界面实时显示排错。
大白话：内核把运行情况写进 mihomo.log，这个模块负责记住"上次读到哪了"，
        每次只读新加的行，省得界面一遍遍把整个文件重读。
"""
import os


class KernelLogTail:
    """包裹一个日志文件，提供"读新增行"的能力。"""

    def __init__(self, path):
        self.path = path
        self.offset = 0  # 上次读到的字节位置

    def reset(self):
        """从头开始读（切换过滤 / 内核重启清空文件时用）。"""
        self.offset = 0

    def read_new(self):
        """
        返回自上次读取以来新增的行（list[str]，不含换行符）。
        两种情况会自动兜底：
          - 文件被清空重写（如内核重启）：当前大小比 offset 小，自动从头读。
          - 文件还不存在（从没启动过内核）：返回空列表，不报错。
        """
        try:
            size = os.path.getsize(self.path)
        except FileNotFoundError:
            return []

        # 文件变小了：多半是内核重启把日志清空重写了，从头读
        if size < self.offset:
            self.offset = 0

        if size == self.offset:
            return []  # 没有新内容

        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self.offset)
                data = f.read()
            self.offset = size  # 读完后把位置推进到文件末尾
            return data.splitlines()
        except OSError:
            return []
