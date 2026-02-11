# RAG系统 - 重构状态说明（API-Only）

## 当前结论

系统已切换为 **API-Only** 运行模式，命令行入口已移除：
- 已删除 `main.py`
- 已删除 `cli_app.py`

当前统一通过 `api_server.py` 启动服务，并由 `src/api/` 目录承载接口层。

## 当前核心架构

1. `api_server.py`：API 启动入口
2. `src/api/app.py`：Flask app 工厂与蓝图注册
3. `src/api/routes/`：按领域拆分路由（system/documents/storage/chat）
4. `src/api/services/rag_service.py`：RAG 生命周期管理与服务编排
5. `src/` 其他分层：保留检索、向量、LLM、解析等核心能力

## 运行方式

```bash
# 构建前端并启动
./start_api.sh

# 不构建前端直接启动
./start_api_no_build.sh

# Linux 后台启动（不构建前端）
./start_api_no_build_daemon.sh 8000 production

# Windows 启动（不构建前端）
start_api_no_build_windows.bat 8000 production
```

## 关键接口

- `GET /health`
- `GET /info`
- `POST /upload_store`
- `GET /documents`
- `DELETE /documents`
- `POST /v1/chat/completions`（支持 SSE 流式）

## 说明

本文件替代历史 CLI 重构说明，后续以 `README.md` 与 `USAGE_GUIDE.md` 为准。
