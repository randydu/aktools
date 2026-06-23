#!/usr/bin/env bash
# Docker entrypoint — starts API server + docs site
set -e

echo "AKTools"
echo "  API:  http://0.0.0.0:8080/docs"
echo "  Docs: http://0.0.0.0:8081"

# ── 数据目录权限检查 ──────────────────────────────────────────
DATA_DIR="${AKTOOLS_DATA_DIR:-/app/data}"
if [ ! -d "$DATA_DIR" ]; then
    echo "ERROR: 数据目录不存在: $DATA_DIR"
    echo "  请检查 AKTOOLS_DATA_DIR 环境变量或卷挂载配置。"
    exit 1
fi
if [ ! -w "$DATA_DIR" ]; then
    echo "ERROR: 数据目录不可写: $DATA_DIR"
    echo "  当前用户: $(id)"
    echo "  目录权限: $(ls -ld "$DATA_DIR")"
    echo ""
    echo "  可能原因：之前以 root 运行，导致文件归 root 所有。"
    echo "  修复方法（在宿主机上执行）："
    echo "    sudo chown -R \$(id -u):\$(id -g) ./data"
    exit 1
fi

# Start API (background)
cd /app/src
gunicorn --bind 0.0.0.0:8080 aktools.main:app -k uvicorn.workers.UvicornWorker &

# Serve pre-built docs (foreground — keeps container alive)
python -m http.server 8081 --directory /app/src/site
