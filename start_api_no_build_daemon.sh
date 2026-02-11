#!/bin/bash
# Linux后台启动HTTP API服务器（跳过前端构建）

PORT=${1:-8000}
MODE=${2:-production}
LOG_FILE=${3:-./logs/api_server.out.log}
PID_FILE=${4:-./api_server.pid}

if [ "$MODE" = "production" ]; then
  export ENVIRONMENT="production"
else
  export ENVIRONMENT="development"
fi

mkdir -p "$(dirname "$LOG_FILE")"

if [ -f "$PID_FILE" ]; then
  OLD_PID=$(cat "$PID_FILE" 2>/dev/null)
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "API已在运行，PID: $OLD_PID"
    exit 1
  fi
fi

nohup python3 api_server.py --host 0.0.0.0 --port "$PORT" >"$LOG_FILE" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"

echo "已后台启动 API 服务"
echo "PID: $NEW_PID"
echo "PORT: $PORT"
echo "MODE: $MODE"
echo "LOG: $LOG_FILE"
