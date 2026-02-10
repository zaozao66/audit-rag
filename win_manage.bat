@echo off
setlocal enabledelayedexpansion

:: RAG系统 - Windows 服务管理脚本
:: 支持启动、停止、重启

set ACTION=%1
set PORT=8000
set MODE=development

if "%ACTION%"=="" (
    echo ===========================================
    echo RAG系统 Windows 服务管理工具
    echo ===========================================
    echo 用法: %~nx0 [start^|stop^|restart] [端口] [模式]
    echo 模式: development (默认), production
    echo 示例: %~nx0 start 8000 development
    echo ===========================================
    goto :eof
)

if not "%2"=="" set PORT=%2
if not "%3"=="" set MODE=%3

if /i "%ACTION%"=="start" (
    call :start_service
) else if /i "%ACTION%"=="stop" (
    call :stop_service
) else if /i "%ACTION%"=="restart" (
    call :stop_service
    timeout /t 2 >nul
    call :start_service
) else (
    echo 未知命令: %ACTION%
    exit /b 1
)

goto :eof

:start_service
echo [信息] 正在启动 RAG API 服务器...
echo [信息] 端口: %PORT%
echo [信息] 模式: %MODE%

:: 检查端口是否被占用
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :%PORT% ^| findstr LISTENING') do (
    echo [错误] 端口 %PORT% 已被 PID 为 %%a 的进程占用。
    exit /b 1
)

:: 设置环境变量
set ENVIRONMENT=%MODE%

:: 启动服务
:: 使用 start 开启新窗口运行，方便查看实时日志
start "RAG-API-Server" python api_server.py --host 0.0.0.0 --port %PORT% --env %MODE%

echo [成功] 服务已在独立窗口启动。
exit /b 0

:stop_service
echo [信息] 正在停止端口 %PORT% 上的 RAG API 服务器...
set FOUND=0
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :%PORT% ^| findstr LISTENING') do (
    taskkill /f /pid %%a
    echo [成功] 已终止 PID 为 %%a 的进程。
    set FOUND=1
)

if %FOUND%==0 (
    echo [警告] 未发现运行在端口 %PORT% 上的服务。
) else (
    echo [成功] 服务已停止。
)
exit /b 0
