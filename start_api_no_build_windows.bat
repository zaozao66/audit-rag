@echo off
REM Windows启动HTTP API服务器（跳过前端构建）

set PORT=%1
if "%PORT%"=="" set PORT=8000

set MODE=%2
if "%MODE%"=="" set MODE=development

if /I "%MODE%"=="production" (
    set ENVIRONMENT=production
) else (
    set ENVIRONMENT=development
)

echo RAG系统 - HTTP API服务器（Windows No Build）
echo PORT: %PORT%
echo MODE: %MODE%
echo ENVIRONMENT: %ENVIRONMENT%
echo.

python api_server.py --host 0.0.0.0 --port %PORT%
