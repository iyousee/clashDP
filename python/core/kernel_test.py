"""
kernel_test.py —— M1 自检脚本（不需要图形界面，新手也能跑）
用法：在 clashDP/python 目录下执行   python -m core.kernel_test
作用：打印关键路径、生成默认配置、检查 mihomo 是否存在、能跑就校验配置语法。
这是 Stage 4 第一步的"验收工具"——你在自己电脑上跑它，看到对应输出就算通过。
"""
import os
import sys
import subprocess
from core import config
from core import kernel


def main():
    print("=== clashDP  M1 内核管理 自检 ===")
    print("项目根目录    :", config.PROJECT_ROOT)
    print("是否打包模式  :", config.IS_PACKAGED)
    print("mihomo 目录   :", config.get_mihomo_dir())
    print("用户配置目录  :", config.get_user_config_dir())
    print("配置文件路径  :", config.get_config_file())

    # 1) 生成一份"临时"配置用来做语法校验
    #    注意：不要写真实的 config.yaml！否则会覆盖你已有的订阅配置，
    #    还可能换掉控制口密钥，导致 APP 与正在运行的内核密钥对不上（401）。
    import tempfile
    tmp_dir = tempfile.mkdtemp(prefix="clashdp_check_")
    cfg_path = kernel.write_config(
        kernel.build_config(tun_enable=False),
        os.path.join(tmp_dir, "config_test.yaml"))
    print("\n[1] 已生成临时测试配置:", cfg_path)

    # 2) 检查 mihomo 二进制是否存在
    mihomo = kernel.find_mihomo()
    if not mihomo:
        print("\n[2] 未找到 mihomo 二进制（这是正常的，开发期还没放）。")
        print("    请把 arm64 版 mihomo 下载后放到:", config.get_mihomo_dir())
        print("    文件名必须是: mihomo （无扩展名）")
        print("    下载地址(架构选 linux-arm64，版本号以官网为准，不确定请核对):")
        print("    https://github.com/MetaCubeX/mihomo/releases")
        print("\nM1 的'路径/配置生成'部分已就绪；放好内核后即可启动。")
        return 0

    print("\n[2] 找到 mihomo:", mihomo)

    # 3) 用 mihomo 自带的 -t 参数校验配置语法
    try:
        r = subprocess.run(
            [mihomo, "-t", "-f", cfg_path],
            capture_output=True, text=True, timeout=30,
        )
        print("[3] 配置校验返回码:", r.returncode)
        if r.stdout.strip():
            print(r.stdout)
        if r.stderr.strip():
            print(r.stderr)
        if r.returncode == 0:
            print("\n[通过] mihomo 配置语法正确，内核可以启动。")
        else:
            print("\n[失败] 配置校验未通过，看上面的报错信息。")
    except Exception as e:
        print("[3] 校验时出错:", e)

    return 0


if __name__ == "__main__":
    sys.exit(main())
