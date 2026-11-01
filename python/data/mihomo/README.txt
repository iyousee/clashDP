这个目录放 mihomo 内核和地理库。内核文件不随仓库提供（体积大），需要自己下载。

最省事的方式：在仓库根目录执行
    ./scripts/fetch-kernel.sh
它会自动识别架构，下载最新版 mihomo 以及 geoip.dat / geosite.dat 放到本目录。

手动下载也可以（以 arm64 为例）：
  mihomo    https://github.com/MetaCubeX/mihomo/releases
            选 mihomo-linux-arm64-vX.Y.Z.gz，解压后重命名为 mihomo
  geoip.dat / geosite.dat
            https://github.com/MetaCubeX/meta-rules-dat/releases/tag/latest

文件到位后目录应该是这样：
  mihomo        （必须可执行：chmod 755 mihomo）
  geoip.dat
  geosite.dat

放好后运行下面这条命令，能看到"找到 mihomo"并校验配置通过，就说明环境齐了：
  cd python && .venv/bin/python -m core.kernel_test
