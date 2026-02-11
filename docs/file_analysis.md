# RAG系统 - 文件结构与功能分析（API-Only）

## 项目结构（关键部分）

```text
audit-rag/
├── api_server.py
├── start_api.sh
├── start_api_no_build.sh
├── start_api_no_build_daemon.sh
├── start_api_no_build_windows.bat
├── config.json
├── requirements.txt
├── frontend/
├── src/
│   ├── api/
│   │   ├── app.py
│   │   ├── routes/
│   │   └── services/
│   ├── core/
│   ├── ingestion/
│   ├── indexing/
│   ├── retrieval/
│   └── llm/
└── data/
```

## 关键文件职责

- `api_server.py`：服务启动入口与基础运行配置。
- `src/api/app.py`：创建 Flask 应用并注册蓝图。
- `src/api/routes/*.py`：按功能域暴露 HTTP 接口。
- `src/api/services/rag_service.py`：管理 RAG 组件生命周期与共享实例。
- `frontend/`：React + Vite 前端，调用后端 API。

## 请求处理链路

1. 请求进入 `src/api/routes/*`。
2. 路由调用 `RAGService` 获取处理器能力。
3. 处理器在 `src/` 业务层执行分块、检索、重排、生成。
4. 返回标准 JSON 或 SSE 流式结果。

## 数据目录

- `data/`：本地持久化目录，存放向量索引与文档元数据。
- 默认为本地运行数据目录，已配置为不纳入 Git 跟踪。
