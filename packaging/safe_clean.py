#!/usr/bin/env python3
"""
safe_clean.py —— 只允许清理"打包临时目录"的小工具

为什么单独写一个：构建过程每次都要把上一次的临时产物删掉重来，
但删除必须限定在 packaging/.tmp/ 里面，绝不能碰到源码、配置或其它目录。
所以这里做了硬性路径校验——只要不在 packaging/.tmp 下，一律拒绝。
"""
import os
import shutil
import sys

ALLOWED = os.path.join("packaging", ".tmp")


def main():
    if len(sys.argv) < 2:
        print("用法: safe_clean.py <要清理的目录>")
        return 2
    for p in sys.argv[1:]:
        ap = os.path.abspath(p)
        if ALLOWED not in ap:
            print("✗ 拒绝清理（不在打包临时目录内）：%s" % ap)
            continue
        if os.path.isdir(ap):
            shutil.rmtree(ap, ignore_errors=True)
            print("  已清理 %s" % os.path.relpath(ap))
    return 0


if __name__ == "__main__":
    sys.exit(main())
