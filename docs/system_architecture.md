# RAG系统架构说明（API-Only）

## 总体结构

```text
Client (Web/Curl)
   |
   v
api_server.py
   |
   v
src/api/app.py (Flask App Factory)
   |
   +--> src/api/routes/system.py
   +--> src/api/routes/documents.py
   +--> src/api/routes/storage.py
   +--> src/api/routes/chat.py
   +--> src/api/routes/audio.py
             |
             v
      src/api/services/rag_service.py
             |
             +--> src/audio/services/speech_script_service.py
             +--> src/audio/services/tts_service.py
             +--> src/audio/services/media_store.py
             +--> src/audio/providers/*
             |
             v
      src/core + src/ingestion + src/indexing(vector+graph) + src/retrieval + src/llm
```

## 典型请求流程

1. 客户端发送 HTTP 请求。
2. Flask 路由接收并做参数校验。
3. `RAGService` 统一管理处理器与依赖初始化。
4. 进入检索/向量/LLM/文档模块执行业务逻辑。
   - 检索支持 `vector / graph / hybrid` 三种模式
5. 可选进入语音模块：
   - 文案层：`/v1/speech/scripts`
   - 合成层：`/v1/audio/speech`（非实时）或 `/v1/audio/speech/realtime`（实时SSE）
   - 媒体层：`/v1/audio/files/<file_name>`
6. 返回 JSON 或 SSE 流式响应（问答/实时语音场景）。

## 设计要点

- 仅保留 API 入口，避免 CLI 与 API 双通道维护成本。
- 路由与服务解耦，便于后续按领域继续拆分。
- 聊天接口支持阶段事件与 token 流式输出，改善等待体验。
- 文档管理支持真实删除与统计查询。
- 语音接口采用分层解耦：文案生成、TTS Provider、媒体输出分离。
- 实时TTS最小版走 Qwen Realtime WebSocket，服务端转为 SSE 事件给前端。

## 启动

```bash
./start_api.sh
./start_api_no_build.sh
./start_api_no_build_daemon.sh 8000 production
start_api_no_build_windows.bat 8000 production
```
