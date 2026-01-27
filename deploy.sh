#!/bin/bash
# RAG系统 - 部署脚本
# 用于在Linux服务器上自动化部署系统

set -e  # 遌输任何命令失败时退出

echo "RAG系统 - 自动部署脚本"
echo "========================"

# 获取当前用户的家目录
HOME_DIR=$(eval echo ~$(whoami))

# 获取当前工作目录
CURRENT_DIR=$(pwd)

# 默认配置
INSTALL_DIR="$HOME_DIR/audit-rag"
SERVICE_NAME="rag-api"
PYTHON_CMD="python3"
PIP_CMD="pip3"

# 检查是否以root身份运行（用于systemd服务安装）
if [[ $EUID -eq 0 ]]; then
    USE_SUDO=""
else
    USE_SUDO="sudo"
fi

# 解析命令行参数
while [[ $# -gt 0 ]]; do
    case $1 in
        -d|--dir)
            INSTALL_DIR="$2"
            shift 2
            ;;
        -p|--port)
            PORT="$2"
            shift 2
            ;;
        --no-service)
            NO_SERVICE=true
            shift
            ;;
        -h|--help)
            echo "用法: $0 [选项]"
            echo "选项:"
            echo "  -d, --dir DIR      指定安装目录 (默认: $HOME_DIR/audit-rag)"
            echo "  -p, --port PORT    指定服务端口 (默认: 8000)"
            echo "  --no-service       仅部署代码，不安装systemd服务"
            echo "  -h, --help         显示此帮助信息"
            exit 0
            ;;
        *)
            echo "未知选项: $1"
            exit 1
            ;;
    esac
done

# 端口默认值
PORT=${PORT:-8000}

echo "安装目录: $INSTALL_DIR"
echo "服务端口: $PORT"
echo ""

# 检查是否已存在安装目录
if [ -d "$INSTALL_DIR" ]; then
    echo "警告: 安装目录 $INSTALL_DIR 已存在"
    read -p "是否覆盖? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "部署已取消"
        exit 1
    fi
    rm -rf "$INSTALL_DIR"
fi

echo "正在复制文件到 $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR"
cp -r ./* "$INSTALL_DIR/"

cd "$INSTALL_DIR"

echo "正在安装Python依赖..."
$PIP_CMD install -r requirements.txt || {
    echo "警告: pip安装失败，尝试使用python -m pip"
    $PYTHON_CMD -m pip install -r requirements.txt
}

echo "正在设置权限..."
chmod +x start_daemon.sh stop_daemon.sh restart_daemon.sh start_api.sh start.sh

# 如果没有指定--no-service，则安装systemd服务
if [ "$NO_SERVICE" != true ]; then
    echo "正在配置systemd服务..."
    
    # 创建服务文件
    SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"
    
    # 检查是否已有服务文件
    if [ -f "$SERVICE_FILE" ]; then
        echo "警告: 服务 $SERVICE_NAME 已存在，正在停止..."
        $USE_SUDO systemctl stop $SERVICE_NAME || true
        $USE_SUDO systemctl disable $SERVICE_NAME || true
    fi
    
    # 创建新的服务文件
    TEMP_SERVICE_FILE=$(mktemp)
    cat > "$TEMP_SERVICE_FILE" << EOF
[Unit]
Description=RAG System API Service
After=network.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$INSTALL_DIR
ExecStart=$PYTHON_CMD $INSTALL_DIR/api_server.py --host 0.0.0.0 --port $PORT
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# 环境变量（根据需要取消注释和修改）
#Environment=PYTHONPATH=$INSTALL_DIR
#Environment=CONFIG_PATH=$INSTALL_DIR/config.json

[Install]
WantedBy=multi-user.target
EOF

    # 复制服务文件到系统目录
    echo "正在复制服务文件到 $SERVICE_FILE ..."
    $USE_SUDO cp "$TEMP_SERVICE_FILE" "$SERVICE_FILE"
    
    # 重新加载systemd配置
    echo "正在重新加载systemd配置..."
    $USE_SUDO systemctl daemon-reload
    
    # 启用服务（开机自启）
    echo "正在启用服务（开机自启）..."
    $USE_SUDO systemctl enable $SERVICE_NAME
    
    # 启动服务
    echo "正在启动服务..."
    $USE_SUDO systemctl start $SERVICE_NAME
    
    # 检查服务状态
    if $USE_SUDO systemctl is-active --quiet $SERVICE_NAME; then
        echo "服务 $SERVICE_NAME 已成功启动并启用开机自启"
    else
        echo "警告: 服务启动失败，请检查日志: sudo journalctl -u $SERVICE_NAME -f"
    fi
    
    # 清理临时文件
    rm "$TEMP_SERVICE_FILE"
else
    echo "跳过systemd服务安装 (--no-service 选项)"
fi

echo ""
echo "部署完成!"
echo "安装位置: $INSTALL_DIR"
echo ""
echo "如果安装了systemd服务，可以使用以下命令管理:"
echo "  查看状态: sudo systemctl status $SERVICE_NAME"
echo "  启动服务: sudo systemctl start $SERVICE_NAME"
echo "  停止服务: sudo systemctl stop $SERVICE_NAME"
echo "  重启服务: sudo systemctl restart $SERVICE_NAME"
echo "  查看日志: sudo journalctl -u $SERVICE_NAME -f"
echo ""
echo "如果使用后台脚本运行，可以使用以下命令:"
echo "  启动: $INSTALL_DIR/start_daemon.sh $PORT"
echo "  停止: $INSTALL_DIR/stop_daemon.sh"
echo "  重启: $INSTALL_DIR/restart_daemon.sh $PORT"
echo ""
echo "API服务可通过 http://localhost:$PORT 访问"