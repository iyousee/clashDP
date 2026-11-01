<p align="center">
  <img src="packaging/clashdp.png" width="96" alt="clashDP">
</p>

<h1 align="center">clashDP</h1>

<p align="center">基于 mihomo (Clash.Meta) 内核的轻量桌面代理客户端 · Python + PySide6</p>

---

## 这是什么

clashDP 是一个运行在 Linux 桌面上的 Clash 图形客户端，用 **Python + PySide6(Qt6)** 写成，界面是原生 Qt 控件，不套浏览器壳，内存占用小、启动快。

它负责指挥 **mihomo**（Clash.Meta 内核）干活：管理订阅、切换节点、开关系统代理、看流量和日志——你用图形界面点，它在后面调度内核。

**主要面向 deepin 23/25 与 Debian 系发行版（arm64 / amd64）。**

## 功能

| 模块 | 说明 |
|---|---|
| 内核管理 | 启动/停止 mihomo，启动前自动用 `mihomo -t` 校验配置，失败时把内核日志直接给你看 |
| 订阅管理 | 支持多订阅、一键更新、定时更新，自动保留 `rule-providers`（规则集不丢） |
| 节点与策略组 | 列表展示、手动切换、批量测延迟；自动识别 `Selector`/`URLTest`/`Fallback` 等组类型 |
| 系统代理 | 通过 gsettings 实时开关，无需重启应用；支持规则 / 全局 / 直连三种模式 |
| 流量监控 | 实时上/下行速度、累计流量、当前连接列表（每 1 秒刷新） |
| 日志面板 | 增量读取内核日志，支持级别过滤、自动滚动开关 |
| TUN 模式 | 全局透明代理，一键检测/授予 `CAP_NET_ADMIN`，启动失败自动降级回系统代理 |
| 托盘常驻 | 关窗不退出，缩到系统托盘后台运行 |
| 中英双语 | 界面可切换中文 / English |

## 安装

### 方式一：安装包（推荐）

从 [Releases](https://github.com/iyousee/clashDP/releases) 下载对应架构的 `.deb`：

```bash
sudo dpkg -i clashdp_x.y.z_arm64.deb
# 若提示缺依赖
sudo apt-get install -f
```

装完在应用菜单搜 **clashDP** 即可。安装脚本会自动给内核授予 TUN 所需权限，装完 TUN 开箱可用。

### 方式二：从源码运行

```bash
git clone https://github.com/iyousee/clashDP.git clashDP
cd clashDP

# 1. 建虚拟环境并装依赖
python3 -m venv python/.venv
python/.venv/bin/pip install -r python/requirements.txt

# 2. 下载内核与地理库（约 75MB）
chmod +x scripts/fetch-kernel.sh
./scripts/fetch-kernel.sh

# 3. 启动
cd python && .venv/bin/python -m app.main
```

> 依赖只有四个：`PySide6`、`requests`、`PyYAML`，以及内核本身。
> `python/data/mihomo/` 下的内核与 `geoip.dat`/`geosite.dat` **不随仓库提供**，用上面的脚本获取。

## 打包成 .deb

```bash
./packaging/build_deb.sh            # 默认版本 1.0.0
./packaging/build_deb.sh 1.0.1      # 指定版本
```

产物在 `dist-deb/`。装之前建议先验收：

```bash
./packaging/verify_deb.sh
```

它会检查包内关键文件、控制信息，并把包解开真实启动一次界面（无头模式）确认能跑。

打包脚本做了一件值得一提的事：完整的 PySide6 有 566MB，打包时会把浏览器内核(WebEngine)、QML、几十国语言翻译、开发工具在**复制阶段**就排除，只留界面真正加载的 89MB，最终安装包约 39MB。

## 目录结构

```
clashDP/
├── python/                 # 主程序
│   ├── app/                # 界面层
│   │   ├── main.py         # 入口：窗口 + 托盘
│   │   └── ui/             # 主窗口、托盘、i18n
│   ├── core/               # 核心逻辑（不依赖 Qt，可单独测试）
│   │   ├── config.py       # 路径分层、设置、密钥持久化
│   │   ├── kernel.py       # 内核启停、配置生成与校验
│   │   ├── mihomo_api.py   # 内核 REST 接口封装
│   │   ├── subscription.py # 订阅解析与配置合并
│   │   ├── nodes.py        # 节点/策略组/测速
│   │   ├── proxy.py        # 系统代理（gsettings）
│   │   ├── traffic.py      # 流量与连接监控
│   │   ├── kernel_log.py   # 日志增量读取
│   │   └── tun.py          # TUN 权限检测与授权
│   └── data/mihomo/        # 内核目录（内核文件需自行下载）
├── packaging/              # 打包工具链
└── scripts/fetch-kernel.sh # 内核下载脚本
```

## 几个实现上的取舍

- **不用 WebSocket**：流量/连接/日志都走 REST 轮询（1 秒一次），少一个依赖，断线重连逻辑也简单。
- **控制口密钥固定**：secret 一次生成后固化到 `settings.json`。早期每次重建配置都随机生成新密钥，导致"配置换了但内核没重启"时接口全部 401。
- **TUN 失败必须降级**：TUN 启动失败会自动关掉 TUN、重建配置、按普通系统代理模式再启动一次，绝不让你卡在打不开的状态。
- **不打包 venv**：venv 里的 `python` 是指向开发机的符号链接，不可移植。安装包用系统 `python3` + 独立依赖目录 `/opt/clashDP/lib` 启动。

## 常见问题

**开了系统代理但上不了网？**
先确认内核已启动。代理指向一个没在跑的端口会造成"全体断网"，关掉系统代理即可恢复。

**TUN 勾了没效果？**
终端执行 `getcap /opt/clashDP/mihomo`，应看到 `cap_net_admin,cap_net_raw,cap_net_bind_service=ep`。没有就在程序的「代理」页点「授权 TUN 权限」。

**自己换了新版内核后 TUN 失效？**
替换二进制会丢掉权限，重新执行：
```bash
sudo setcap cap_net_admin,cap_net_raw,cap_net_bind_service=+ep /opt/clashDP/mihomo
```

**节点延迟全是超时？**
部分节点禁 ping / 禁测速接口，属正常现象。

**Linux 下连接列表的"进程"列是空的？**
未开 TUN 时内核拿不到进程名，这是内核限制，不是 bug。

## 免责声明

本项目仅作为 mihomo 内核的图形前端，**不提供任何代理服务、订阅或节点**。请在遵守所在地区法律法规的前提下使用。使用本软件产生的一切后果由使用者自行承担。

## 许可

本项目以 **GPL-3.0** 发布（因其分发/调用的 mihomo 内核采用 GPL-3.0）。
PySide6 采用 LGPL-3.0，Qt 采用 LGPL/GPL 双许可。

详见 [LICENSE](LICENSE)。

## 致谢

- [mihomo](https://github.com/MetaCubeX/mihomo) —— Clash.Meta 内核
- [MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat) —— GeoIP / GeoSite 数据
- [PySide6](https://doc.qt.io/qtforpython/) —— Qt for Python
