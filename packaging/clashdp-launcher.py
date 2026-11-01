#!/usr/bin/env python3
"""
clashdp-launcher.py —— 打包后的程序入口
说明：安装到 /opt/clashDP/clashdp-launcher.py，由 /usr/bin/clashdp 调用。

它干三件事：
  1. 把 /opt/clashDP（app、core 两个包）和 /opt/clashDP/lib（PySide6 等依赖）
     加进 Python 的搜索路径；
  2. 打上 CLASHDP_PACKAGED=1 标记，让 config.py 知道"现在是安装后的环境"，
     从而把 mihomo 找在 /opt/clashDP、用户配置写到 ~/.config/clashDP；
  3. 启动真正的图形界面。
"""
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))

# 先标记"已打包"，再导入我们的代码 —— 顺序不能反，
# 因为 config.py 是一被导入就读取这个环境变量的。
os.environ.setdefault("CLASHDP_PACKAGED", "1")

# 依赖库目录优先级最高，其次是程序自身目录
sys.path.insert(0, os.path.join(BASE, "lib"))
sys.path.insert(0, BASE)

from app.main import main  # noqa: E402  （必须在设置好路径后再导入）

if __name__ == "__main__":
    main()
