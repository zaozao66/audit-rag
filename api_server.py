"""
RAG系统 - HTTP API入口

第一阶段重构：
- 路由拆分到 src/api/routes
- rag_processor 生命周期管理下沉到 src/api/services/rag_service.py
- 本文件仅负责应用创建与启动
"""

import argparse
import logging
import os

from src.api.app import create_app


def configure_logging() -> logging.Logger:
    env = os.getenv('ENVIRONMENT', 'development')
    if env == 'production':
        log_file = '/data/appLogs/api_server.log'
    else:
        log_file = './logs/api_server.log'

    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError:
            if env == 'production':
                log_file = './logs/api_server.log'
                log_dir = os.path.dirname(log_file)
                if log_dir and not os.path.exists(log_dir):
                    os.makedirs(log_dir, exist_ok=True)

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    try:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
    except OSError:
        file_handler = None

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    if file_handler:
        logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


logger = configure_logging()
app = create_app()
app.logger.handlers = logger.handlers
app.logger.setLevel(logger.level)


def run_server(host: str = '0.0.0.0', port: int = 8000):
    logger.info("启动HTTP API服务器，地址: %s:%s", host, port)

    try:
        service = app.extensions['rag_service']
        service.get_processor()
        logger.info("RAG处理器预初始化完成")
    except Exception as e:
        logger.error("RAG处理器预初始化失败: %s", e)
        logger.info("将在首次请求时初始化")

    app.run(host=host, port=port, debug=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='RAG系统HTTP API服务器')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='服务器主机地址 (默认: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=8000, help='服务器端口 (默认: 8000)')
    parser.add_argument('--env', type=str, default=None, help='运行环境 (production 或 development)')
    args = parser.parse_args()

    if args.env:
        os.environ['ENVIRONMENT'] = args.env

    run_server(host=args.host, port=args.port)
