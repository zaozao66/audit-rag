#!/bin/bash
# 启动HTTP API服务器（跳过前端构建）

echo "RAG系统 - HTTP API服务器（No Build）"
echo "===================================="

# 检查是否提供了端口号参数和环境模式参数
PORT=${1:-8000}
MODE=${2:-development}  # 默认为开发模式

# 根据模式设置环境变量
if [ "$MODE" = "production" ]; then
    export ENVIRONMENT="production"
    echo "启动生产环境模式"
else
    export ENVIRONMENT="development"
    echo "启动开发环境模式"
fi

echo "启动API服务器，端口: $PORT"
echo "模式: $MODE"
echo "说明: 本脚本不会执行前端构建，直接启动后端"
echo ""

python3 api_server.py --host 0.0.0.0 --port "$PORT"
