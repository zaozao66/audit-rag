#!/bin/bash
# RAG系统 - 重启后台运行的API服务器

echo "正在重启API服务器..."

# 先停止服务
./stop_daemon.sh

# 等待一段时间确保进程完全停止
sleep 3

# 启动服务
if [ $# -gt 0 ]; then
    ./start_daemon.sh $1 $2
else
    ./start_daemon.sh
fi