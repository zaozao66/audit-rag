#!/bin/bash
# RAG系统 - 后台运行HTTP API服务器
# 用于在Linux服务器上部署

# 默认配置
PORT=${1:-8000}
MODE=${2:-development}  # 默认为开发模式

# 根据模式设置日志文件
if [ "$MODE" = "production" ]; then
    LOG_FILE="/data/appLogs/api_server.log"
    export ENVIRONMENT="production"
    echo "启动生产环境模式"
else
    LOG_FILE="./logs/api_server.log"
    export ENVIRONMENT="development"
    echo "启动开发环境模式"
fi

PID_FILE="./api_server.pid"

# 创建日志目录
if [ "$MODE" = "production" ]; then
    # 创建生产环境日志目录
    sudo mkdir -p /data/appLogs
    sudo chmod 755 /data/appLogs
else
    # 创建开发环境日志目录
    mkdir -p logs
fi

# 检查进程是否已在运行
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p $PID > /dev/null 2>&1; then
        echo "API服务器已在运行 (PID: $PID)"
        exit 1
    else
        # PID文件存在但进程不在运行，清理PID文件
        rm -f "$PID_FILE"
    fi
fi

echo "RAG系统 - HTTP API服务器 (后台运行)"
echo "==================================="
echo "启动API服务器，端口: $PORT"
echo "模式: $MODE"
echo "日志文件: $LOG_FILE"
echo "PID文件: $PID_FILE"

# 启动API服务器并将其置于后台
nohup python3 api_server.py --host 0.0.0.0 --port $PORT >> "$LOG_FILE" 2>&1 &

# 保存进程ID
SERVER_PID=$!
echo $SERVER_PID > "$PID_FILE"

echo "API服务器已启动 (PID: $SERVER_PID)，运行在端口 $PORT"
echo "API端点:"
echo "  POST /store   - 存储文档"
echo "  POST /search  - 搜索文档" 
echo "  POST /clear   - 清空向量库"
echo "  GET  /health  - 健康检查"
echo "  GET  /info    - 系统信息"
echo ""
echo "查看日志: tail -f $LOG_FILE"
echo "停止服务器: ./stop_daemon.sh"