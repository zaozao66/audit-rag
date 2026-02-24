# Audit RAG

这是一个面向审计/合规场景的 RAG 系统，支持文档入库、检索、意图识别、LLM 问答（含流式响应）和文档生命周期管理。

## 功能特性

- 支持PDF、DOCX和TXT格式文档处理
- 使用text-embedding-v4模型生成文档向量
- 使用Faiss进行高效的向量相似性搜索
- 支持中文文档处理
- 可配置的文档分块策略
- **意图驱动搜索**：识别用户意图并动态路由至不同库（制度/报告/问题库）
- **重排序增强**：集成rerank模型提升相关性
- **GraphRAG 混合检索**：支持 `vector / graph / hybrid` 三种检索模式，可做多跳关联召回
- **LLM智能问答**：基于意图识别和检索结果生成精准回答
- **持久化向量库**：支持增量上传与自动加载
- **HTTP API接口**：提供 RESTful API，支持流式问答与文档管理

## 安装依赖

```bash
pip install -r requirements.txt
```

## 配置

编辑`config.json`文件，填入你的API密钥：

```json
{
  "embedding_model": {
    "api_key": "your-api-key-here"
  }
}
```

## 使用方法

### API 接口

启动HTTP API服务器：

```bash
# 默认端口8000（会先构建前端）
./start_api.sh

# 或指定端口
./start_api.sh 9000

# 不构建前端，直接启动
./start_api_no_build.sh

# Linux 后台启动（不构建前端）
./start_api_no_build_daemon.sh 8000 production

# Windows 启动（不构建前端）
start_api_no_build_windows.bat 8000 production
```

API端点：

- `GET  /health` - 健康检查
- `POST /store` - 存储文档
- `POST /upload_store` - (推荐) 上传并存储文档(文件)
- `POST /search_with_intent` - 意图识别搜索
- `POST /ask` - 非流式LLM问答
- `POST /v1/chat/completions` - OpenAI兼容问答（支持流式SSE）
- `POST /clear` - 清空向量库
- `POST /graph/rebuild` - 重建 GraphRAG 图索引
- `GET  /info` - 系统信息
- `GET  /documents` - 文档列表（支持类型/关键字/是否含已删除过滤）
- `DELETE /documents` - 清空全部文档（真实删除向量与元数据）
- `GET  /documents/<doc_id>` - 文档详情
- `DELETE /documents/<doc_id>` - 删除文档
- `GET  /documents/<doc_id>/chunks` - 文档分块详情
- `GET  /documents/stats` - 文档统计

#### 流式问答示例（推荐）

```bash
curl -N -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role":"user","content":"请总结审计风险重点"}],
    "stream": true
  }'
```

说明：
- 返回类型为 `text/event-stream`
- 会先返回阶段进度事件（`intent` / `retrieval` / `generation`），再返回 `delta.content` 文本分片

#### 存储文档API示例

```bash
curl -X POST http://localhost:8000/store \
  -H "Content-Type: application/json" \
  -d '{
    "documents": [
      {
        "doc_id": "doc_1",
        "title": "文档标题",
        "text": "这里是文档的文本内容...",
        "source": "example_source"
      }
    ]
  }'
```

#### 智能搜索API示例：

```bash
curl -X POST http://localhost:8000/search_with_intent \
  -H "Content-Type: application/json" \
  -d '{
    "query": "采购管理有哪些制度要求？",
    "retrieval_mode": "hybrid",
    "graph_hops": 2,
    "hybrid_alpha": 0.65
  }'
```

`retrieval_mode` 可选值：
- `vector`：仅向量检索（默认）
- `graph`：仅图检索（多跳实体关系）
- `hybrid`：向量 + 图融合检索（推荐）

#### 重建图索引示例

```bash
curl -X POST http://localhost:8000/graph/rebuild
```

#### 清空向量库API示例：

```bash
curl -X POST http://localhost:8000/clear
```

## 项目结构（当前）

```
audit-rag/
├── api_server.py           # HTTP API服务器
├── start_api.sh            # 启动API（含前端构建）
├── start_api_no_build.sh   # 启动API（不构建前端）
├── start_api_no_build_daemon.sh   # Linux后台启动（不构建前端）
├── start_api_no_build_windows.bat # Windows启动（不构建前端）
├── config.json             # 配置文件
├── requirements.txt        # 依赖包列表
├── frontend/               # React + Vite 前端工程（构建产物由后端托管）
├── src/                    # 源代码分层结构
│   ├── api/                # API层（第一阶段重构）
│   │   ├── app.py          # Flask app 工厂与蓝图注册
│   │   ├── routes/         # 按领域拆分路由（chat/documents/storage/system）
│   │   └── services/       # API 服务层（RAGService 生命周期管理）
│   ├── core/               # 核心层：抽象定义与组件工厂 (Factory Pattern)
│   │   ├── factory.py      # 组件创建工厂
│   │   ├── interfaces.py   # 接口契约定义
│   │   └── schemas.py      # 数据模型定义
│   ├── ingestion/          # 解析层：文档解析与分块
│   │   ├── parsers/        # 文档格式解析 (支持 PDF 表格逻辑聚合)
│   │   └── splitters/      # 智能分块策略 (制度模式、审计报告模式、台账模式)
│   ├── indexing/           # 存储层：向量化与持久化
│   │   ├── vector/         # 向量数据库实现与 Embedding Provider
│   │   └── graph/          # GraphRAG 图索引构建与检索
│   ├── retrieval/          # 检索层：搜索、路由与重排
│   │   ├── router/         # 意图路由 (Intent Routing) 与流程编排
│   │   ├── searchers/      # 具体检索策略实现
│   │   └── rerank/         # 重排序提供者实现
│   ├── llm/                # 生成层：大语言模型集成
│   │   └── providers/      # 各类模型厂商 (OpenAI/DeepSeek 等) 接入
│   └── utils/              # 工具层：基础辅助功能
└── data/                   # 本地数据目录（已默认忽略，不纳入 Git）
```

## 技术架构

- **文档处理**：支持 PDF（含表格逻辑聚合）、DOCX、TXT 格式解析
- **分块策略**：基于语义边界的智能分块，内置制度（章/节/条）、报告（一/（一））、审计台账（逻辑行）等专项优化
- **嵌入模型**：厂商中立设计，支持 text-embedding-v4、BGE 等多种 Embedding 模型
- **向量存储**：基于 Faiss 的高效向量检索，支持元数据过滤与持久化
- **检索增强**：集成意图路由 (Intent Routing)、GraphRAG 多跳扩展与多级重排序 (Rerank) 机制
- **接口规范**：提供 RESTful 标准接口，并兼容 OpenAI Chat Completions 协议（支持流式响应）
