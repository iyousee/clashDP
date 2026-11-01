#!/bin/bash
# =============================================================================
# fetch-kernel.sh —— 一键下载 mihomo 内核与地理库
#
# 仓库里不放 55MB 的内核二进制（GitHub 单文件上限 100MB，且每次升级都会
# 撑大 git 历史）。所以克隆完代码后，跑一次这个脚本把内核拿到本地即可。
#
# 用法：
#   ./scripts/fetch-kernel.sh                 # 自动下载最新版（当前架构）
#   ./scripts/fetch-kernel.sh v1.19.33        # 指定版本
#
# 下载到：python/data/mihomo/
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="$HERE/../python/data/mihomo"
mkdir -p "$DEST"

# ---------- 判断架构 ----------
case "$(uname -m)" in
    aarch64|arm64) ARCH="arm64" ;;
    x86_64|amd64)  ARCH="amd64" ;;
    386|i686)      ARCH="386" ;;
    *) echo "✗ 不认识的架构：$(uname -m)"; exit 1 ;;
esac

VERSION="${1:-}"
API="https://api.github.com/repos/MetaCubeX/mihomo/releases/latest"

# ---------- 找下载地址 ----------
echo "正在查询 mihomo 版本（架构：linux-$ARCH）..."
if [ -z "$VERSION" ]; then
    VERSION="$(curl -fsSL "$API" | grep -m1 '"tag_name"' | sed 's/.*"\(v[^"]*\)".*/\1/')"
fi
if [ -z "$VERSION" ]; then
    echo "✗ 查不到版本号，请检查网络，或手动指定：$0 v1.19.33"
    exit 1
fi
echo "目标版本：$VERSION"

# 官方文件名形如 mihomo-linux-arm64-v1.19.33.gz
URL="https://github.com/MetaCubeX/mihomo/releases/download/${VERSION}/mihomo-linux-${ARCH}-${VERSION}.gz"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP" 2>/dev/null || true' EXIT

echo "下载内核：$URL"
if ! curl -fL --progress-bar -o "$TMP/mihomo.gz" "$URL"; then
    echo "✗ 下载失败。可能是文件名规则不同，请打开下面的页面手动下载："
    echo "  https://github.com/MetaCubeX/mihomo/releases/tag/${VERSION}"
    echo "  选 mihomo-linux-${ARCH}-${VERSION}.gz，解压后把文件放到：$DEST/mihomo"
    exit 1
fi

gunzip -f "$TMP/mihomo.gz"
install -m 755 "$TMP/mihomo" "$DEST/mihomo"
echo "✓ 内核已放到 $DEST/mihomo"

# ---------- 地理库（GEOIP/GEOSITE 规则要用）----------
for name in geoip.dat geosite.dat; do
    echo "下载地理库：$name"
    if curl -fL --progress-bar -o "$DEST/$name" \
        "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/$name"; then
        chmod 644 "$DEST/$name"
        echo "✓ $name"
    else
        echo "! $name 下载失败，首次启动内核时它也会自动尝试下载"
    fi
done

echo
echo "完成。可以运行了："
echo "  cd python && .venv/bin/python -m app.main"
echo "（第一次先按 README 建好虚拟环境并装依赖）"
