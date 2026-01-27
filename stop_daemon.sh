#!/bin/bash
# RAG系统 - 停止后台运行的API服务器

PID_FILE="./api_server.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "API服务器未运行 (PID文件不存在)"
    exit 1
fi

PID=$(cat "$PID_FILE")

if ps -p $PID > /dev/null 2>&1; then
    echo "正在停止API服务器 (PID: $PID)..."
    kill $PID
    
    # 等待进程终止
    sleep 2
    
    # 再次检查进程是否还存在
    if ps -p $PID > /dev/null 2>&1; then
        echo "进程仍在运行，强制终止..."
        kill -9 $PID
    fi
    
    # 删除PID文件
    rm -f "$PID_FILE"
    echo "API服务器已停止"
else
    echo "API服务器未运行 (PID $PID 不存在)"
    # 清理可能过期的PID文件
    rm -f "$PID_FILE"
fi