# RAG系统使用说明

## 项目结构

```
audit-rag/
├── main.py                 # 主程序入口（命令行接口）
├── api_server.py           # HTTP API服务器
├── start_api.sh            # 启动API（含前端构建）
├── start_api_no_build.sh   # 启动API（不构建前端）
├── start_api_no_build_daemon.sh   # Linux后台启动（不构建前端）
├── start_api_no_build_windows.bat # Windows启动（不构建前端）
├── cli_app.py              # 命令行接口应用程序
├── config.json             # 配置文件
├── requirements.txt        # 依赖包列表
├── src/                    # 源代码分层结构
│   ├── core/               # 核心层：抽象定义与组件工厂 (Factory Pattern)
│   │   ├── factory.py      # 组件创建工厂
│   │   ├── interfaces.py   # 接口契约定义
│   │   └── schemas.py      # 数据模型定义
│   ├── ingestion/          # 解析层：文档解析与分块
│   │   ├── parsers/        # 文档格式解析 (支持 PDF 表格逻辑聚合)
│   │   └── splitters/      # 智能分块策略 (制度模式、审计报告模式、台账模式)
│   ├── indexing/           # 存储层：向量化与持久化
│   │   └── vector/         # 向量数据库实现与 Embedding Provider
│   ├── retrieval/          # 检索层：搜索、路由与重排
│   │   ├── router/         # 意图路由 (Intent Routing) 与流程编排
│   │   ├── searchers/      # 具体检索策略实现
│   │   └── rerank/         # 重排序提供者实现
│   ├── llm/                # 生成层：大语言模型集成
│   │   └── providers/      # 各类模型厂商 (OpenAI/DeepSeek 等) 接入
│   └── utils/              # 工具层：基础辅助功能
└── data/                   # 数据目录 (存放持久化 Faiss 索引及文档映射)
```

## 功能特性

1. **文档存储**：将文档内容转换为向量并存储到向量数据库
2. **意图驱动搜索**：利用LLM识别用户查询意图（如制度查询、报告分析等），自动优化搜索参数
3. **重排序搜索**：使用 rerank 模型对搜索结果进行精准排序，支持针对不同意图的动态重排策略
4. **LLM问答**：基于意图识别和检索结果，使用大模型生成具备可追溯性的智能回答
5. **多文件支持**：支持同时处理多个文档，支持中文文件名保留
6. **持久化存储**：向量库自动加载与追加，支持跨会话增量存储
7. **HTTP API接口**：提供现代化的RESTful API，支持智能搜索与问答
8. **智能分块**：根据文档类型自动选择合适的分块策略
   - 法规制度：按章、节、条结构分块
   - 审计报告：按报告层级结构（一、（一）、1.）分块
   - 普通文档：按段落和语义边界分块
9. **文档类型管理**：支持标记文档类型（内部制度、外部制度、内部报告、外部报告）并按类型过滤检索

## 文档类型说明

系统支持以下四种文档类型，并为每种类型提供智能分块策略：

### 1. 内部制度 (`internal_regulation`)
- 企业内部的规章制度、管理办法、操作规程等
- 使用法规文档分块器，按照"第X章"、"第X节"、"第X条"等结构进行分块
- 保持条款的完整性和逻辑连贯性

### 2. 外部制度 (`external_regulation`)
- 国家法律法规、行业标准、监管要求等外部规范性文件
- 同内部制度，使用法规文档分块器
- 适合处理《中华人民共和国XX法》、《XX管理办法》等文档

### 3. 内部报告 (`internal_report`)
- 企业内部的审计报告、检查报告、评估报告等
- 使用审计报告分块器，按照"一、二、三、..."和"（一）（二）..."层级结构分块
- 保持报告章节的完整性

### 4. 外部报告 (`external_report`)
- 审计署报告、监管机构检查报告等外部报告
- 同内部报告，使用审计报告分块器
- 特别适合处理政府审计报告、行业检查报告等结构化文档

### 5. 审计问题 (`audit_issue`)
- 专门用于处理“审计发现问题整改情况表”等表格类文档
- 使用审计问题分块器，识别表格中的每一行记录（序号+问题摘要+整改情况）作为一个独立的检索单元
- 适合处理历史问题台账、外部审计整改通报等文档

**智能识别**：即使不指定文档类型，系统也会根据文档内容自动识别并选择合适的分块策略。

## 使用方法

### 1. 命令行接口

#### 存储文档

将文档存储到向量库：

```bash
python main.py store --files /path/to/doc1.pdf /path/to/doc2.docx --chunker-type smart
```

参数说明：
- `--files`: 文件路径列表
- `--chunker-type`: 分块器类型，可选：
  - `default`: 普通分块逻辑
  - `regulation`: 制度文件分块逻辑（适用于法规、内部制度等）
  - `audit_report`: 审计报告分块逻辑（适用于各类审计报告）
  - `smart`: (推荐) 智能识别文档类型并选择最优逻辑
- `--store-path`: 自定义向量库存储路径

#### 搜索文档

从向量库中搜索相关文档：

```bash
python main.py search --query "你的查询内容"
```

交互式搜索模式：

```bash
python main.py search
```

指定自定义向量库路径：

```bash
python main.py search --query "查询内容" --store-path ./my_custom_store
```

#### 清空向量库

清空现有向量库：

```bash
python main.py clear
```

指定自定义向量库路径：

```bash
python main.py clear --store-path ./my_custom_store
```

### 2. HTTP API接口

启动HTTP API服务器：

```bash
# 默认端口8000
./start_api.sh

# 指定端口
./start_api.sh 9000
```

#### API端点

**系统管理**
- `GET  /health` - 健康检查
- `GET  /info` - 获取系统信息（包括当前分块器类型、模型等）

**文档管理**
- `POST /store` - 存储文档(JSON格式)
- `POST /upload_store` - 上传并存储文档(文件上传)
- `POST /clear` - 清空向量库

**测试工具**
- `POST /chunk_test` - 测试文档分块功能(文本输入)
- `POST /chunk_test_upload` - 测试文档分块功能(文件上传)

**智能问答**
- `POST /search_with_intent` - (推荐) 意图识别智能搜索
- `POST /ask` - 意图驱动LLM问答
- `POST /v1/chat/completions` - OpenAI兼容问答接口（支持流式/非流式）

#### 存储文档API

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
    ],
    "chunker_type": "smart"
  }'
```

#### 上传并存储文档API (支持多文件与中文名)

支持直接上传文件进行存储，支持PDF、DOCX、TXT等格式，且完整保留中文文件名：

```bash
curl -X POST http://localhost:8000/upload_store \
  -F "files=@/path/to/审计报告2024.pdf" \
  -F "files=@/path/to/管理制度.docx" \
  -F "chunker_type=smart" \
  -F "doc_type=external_report" \
  -F "save_after_processing=true"
```

参数说明：
- `files`: 要上传的一个或多个文件（支持中文名）
- `chunker_type`: (可选) 分块器类型：
  - `smart`: (推荐) 智能识别文档内容并选择最优策略
  - `regulation`: 制度模式（处理法规、内部规章、章/节/条结构）
  - `audit_report`: 审计报告模式（处理专项审计报告、一/（一）/1.层级）
  - `audit_issue`: 审计问题模式（处理整改情况表、表格行结构）
  - `default`: 普通段落分块
- `doc_type`: (可选) 文档类型标记（用于过滤）：internal_regulation, external_regulation, internal_report, external_report, audit_issue
- `save_after_processing`: (可选) 处理后是否自动保存，默认为true
- `store_path`: (可选) 自定义向量库存储路径


#### 测试文档分块API (文本测试)

用于测试分块效果，不实际存储到向量库：

```bash
curl -X POST http://localhost:8000/chunk_test \
  -H "Content-Type: application/json" \
  -d '{
    "text": "这里是需要分块的文档内容...",
    "chunker_type": "law",
    "chunk_size": 512,
    "overlap": 50
  }'
```

参数说明：
- `text`: (必需) 要分块的文档文本内容
- `chunker_type`: (可选) 分块器类型（见上文），默认为 `smart`
  - `regulation`: 制度文件模式
  - `audit_report`: 审计报告模式
  - `default`: 普通分块模式
- `chunk_size`: (可选) 分块大小，默认为512
- `overlap`: (可选) 块间重叠大小，默认为50

返回结果包含分块的数量、每个块的预览以及分块详情.


#### 上传文件测试文档分块API (文件测试)

用于上传文件并测试分块效果，不实际存储到向量库：

```bash
curl -X POST http://localhost:8000/chunk_test_upload \
  -F "file=@/path/to/审计报告.docx" \
  -F "chunker_type=audit" \
  -F "chunk_size=1024"
```

参数说明与 `upload_store` 一致。

返回结果包含文件信息、分块的数量、每个块的预览以及分块详情.

#### 意图识别智能搜索API (推荐)

系统会自动通过LLM识别您的查询意图，并动态调整检索范围（库筛选）和检索深度（top_k）：

```bash
curl -X POST http://localhost:8000/search_with_intent \
  -H "Content-Type: application/json" \
  -d '{
    "query": "基于审计报告，分析公司目前面临的TOP3风险"
  }'
```

#### 智能搜索接口功能

1. **自动库筛选**：根据意图决定搜索 `internal_regulation` 还是 `internal_report` 库。
2. **动态检索深度**：普通查询 `top_k=5`，分析类查询自动提升至 `top_k=20`。
3. **分阶段优化**：集成向量检索 -> 元数据过滤 -> LLM 意图识别 -> 结果重排序的全链路。
4. **兼容性响应**：支持标准 JSON 格式及符合 OpenAI 规范的消息流。

#### LLM问答API

使用大模型基于意图识别和检索结果生成智能回答：

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{
    "query": "采购管理有哪些问题？"
  }'
```

**特性说明：**
- **自动路由**：系统会自动判断问题属于制度还是审计报告，并动态决定 `top_k`。
- **可追溯性**：回答中的引用部分会直接显示**来源文件名**，而非序号。
- **安全限制**：针对第三方重排序API（如阿里云）的文档数量（10个）和字符长度限制进行了自动截断处理。

返回结果格式：
```json
{
  "success": true,
  "query": "采购管理有哪些问题？",
  "intent": "audit_query",
  "answer": "基于《2024年采购专项审计报告》，采购管理主要存在以下问题：\n\n1. 采购计划管理不规范...",
  "search_results": [
    {
      "score": 0.95,
      "text": "相关文档内容...",
      "doc_type": "internal_report",
      "title": "2024年采购专项审计报告",
      "filename": "2024年采购专项审计报告.pdf"
    }
  ],
  "llm_usage": {
    "prompt_tokens": 1200,
    "completion_tokens": 300,
    "total_tokens": 1500
  },
  "model": "deepseek-chat"
}
```

**注意**：使用LLM问答功能前，需要在 `config.json` 中配置LLM API密钥。

#### OpenAI兼容问答API（推荐用于前端集成）

系统提供完全兼容 OpenAI Chat Completions API 的接口，支持流式和非流式两种响应模式：

**非流式请求示例：**

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "请介绍一下个人信息保护法的主要内容"}
    ],
    "stream": false,
    "top_k": 5
  }'
```

**流式请求示例：**

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -N \
  -d '{
    "messages": [
      {"role": "user", "content": "审计法的适用范围是什么？"}
    ],
    "stream": true,
    "top_k": 5
  }'
```

**请求参数说明：**
- `messages`: (必需) 消息列表，格式为 `[{"role": "user", "content": "问题"}]`
  - 支持多轮对话，系统会自动提取最后一条用户消息
- `stream`: (可选) 是否使用流式响应，默认为 `false`
- `top_k`: (可选) 检索文档数量，默认为 5

**非流式响应格式：**

```json
{
  "choices": [{
    "message": {
      "role": "assistant",
      "content": "这是助手的回复内容"
    },
    "finish_reason": "stop",
    "index": 0
  }],
  "model": "deepseek-chat",
  "usage": {
    "prompt_tokens": 120,
    "completion_tokens": 80,
    "total_tokens": 200
  },
  "intent": "regulation_query"
}
```

**流式响应格式（SSE）：**

```
data: {"choices":[{"delta":{"content":"这"},"index":0,"finish_reason":null}]}

data: {"choices":[{"delta":{"content":"是助手"},"index":0,"finish_reason":null}]}

data: {"choices":[{"delta":{"content":"的回复"},"index":0,"finish_reason":null}]}

data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}]}

data: [DONE]
```

**核心特性：**
- ✅ 完全兼容 OpenAI API 格式，便于前端直接对接
- ✅ 自动意图识别和路由
- ✅ 支持流式输出，提升用户体验
- ✅ 集成重排序和智能检索能力

#### 配置LLM

在 `config.json` 中添加或修改 `llm_model` 配置：

```json
{
  "development": {
    "llm_model": {
      "provider": "deepseek",
      "model_name": "deepseek-chat",
      "api_key": "YOUR_DEEPSEEK_API_KEY_HERE",
      "endpoint": "https://api.deepseek.com/v1",
      "temperature": 0.7,
      "max_tokens": 2000,
      "ssl_verify": true
    }
  }
}
```

请将 `YOUR_DEEPSEEK_API_KEY_HERE` 替换为你的实际 DeepSeek API 密钥。

参数说明：
- `query`: (必需) 搜索查询文本
- `top_k`: (可选) 返回前k个结果，默认为5
- `rerank_top_k`: (可选) 重排序时考虑的文档数量，默认为10
- `doc_types`: (可选) 文档类型过滤列表，支持：internal_regulation（内部制度）、external_regulation（外部制度）、internal_report（内部报告）、external_report（外部报告）
- `titles`: (可选) 标题过滤列表，只返回指定标题的文档

搜索结果格式：
- `score`: 重排序后的相关性分数
- `text`: 匹配的文本内容
- `doc_id`: 文档ID
- `filename`: 文件名
- `file_type`: 文件类型
- `doc_type`: 文档类型
- `title`: 文档标题
- `original_score`: (可选) 原始相似度分数（当使用重排序时）

#### 清空向量库API

```bash
curl -X POST http://localhost:8000/clear
```

### 3. Linux服务器部署

系统支持在Linux服务器上后台运行，便于长期部署。

#### 后台运行模式（无前端构建）

启动后台服务（默认端口8000）：

```bash
# 启动后台服务
./start_api_no_build_daemon.sh

# 指定端口启动后台服务
./start_api_no_build_daemon.sh 9000 production
```

停止后台服务（按 PID 文件）：

```bash
kill "$(cat api_server.pid)"
```

重启后台服务：

```bash
kill "$(cat api_server.pid)"
./start_api_no_build_daemon.sh 9000 production
```

查看服务状态和日志：

```bash
# 查看运行日志
tail -f logs/api_server.log

# 查看进程状态
ps aux | grep api_server
```

#### 后台运行特性

- 服务在后台持续运行，不会因终端关闭而停止
- 自动将日志输出到 `logs/api_server.out.log` 文件（可通过脚本参数自定义）
- 使用PID文件跟踪进程状态，防止重复启动
- 支持通过 PID 文件进行停止和重启

#### 使用 systemd 部署 (推荐用于生产环境)

对于Linux服务器，推荐使用systemd服务进行部署，这种方式更稳定可靠。

##### 手动部署

如果你不想使用自动化脚本，也可以手动部署：

1. 编辑 `rag-api.service.example` 文件，修改其中的路径和用户名：

```bash
# 编辑服务配置
nano rag-api.service.example
```

将其中的 `your_username` 替换为实际用户名，将路径替换为实际部署路径。

2. 复制服务文件到systemd目录：

```bash
sudo cp rag-api.service.example /etc/systemd/system/rag-api.service
```

3. 重新加载systemd配置：

```bash
sudo systemctl daemon-reload
```

4. 启动服务：

```bash
sudo systemctl start rag-api
```

5. 设置开机自启：

```bash
sudo systemctl enable rag-api
```

6. 查看服务状态：

```bash
sudo systemctl status rag-api
```

7. 查看服务日志：

```bash
sudo journalctl -u rag-api -f
```

systemd服务方式提供了更好的进程管理和系统集成，适合在生产环境中使用.

#### 4. Windows环境部署

针对 Windows 环境，提供了无前端构建启动脚本：

```batch
# 启动服务 (默认端口8000, 开发模式)
start_api_no_build_windows.bat

# 指定端口和模式启动
start_api_no_build_windows.bat 9000 production
```

停止服务请在 Windows 中结束对应 Python 进程（任务管理器或命令行）。

## 环境模式与配置说明

系统支持开发和生产两种环境模式，配置从 `config.json` 文件中读取：

#### 环境配置差异

| 配置项 | 开发环境 (`development`) | 生产环境 (`production`) |
|--------|----------|----------|
| 日志路径 | `./logs/api_server.log` | `/data/appLogs/api_server.log` |  
| 嵌入模型 | `text-embedding-v4` | `bge` |
| 重排序模型 | `qwen3-rerank` | `bge-reranker-large` |
| API密钥 | `sk-60bf45825e4442728dc3431b1ffba0bc` | `sk-HiOOuMeh9lTdxW6v` |
| 端点 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `https://ai-llm.nucc.com/v1/models` |
| SSL验证 | 启用 | 禁用 |

#### 启动方式

**命令行启动：**

开发环境：
```bash
python api_server.py --host 0.0.0.0 --port 8000 --env development
```

生产环境：
```bash
python api_server.py --host 0.0.0.0 --port 8000 --env production
```

**使用启动脚本：**

开发环境：
```bash
./start_api.sh 8000 development
```

生产环境：
```bash
./start_api.sh 8000 production
```

**后台运行：**

开发环境：
```bash
./start_api_no_build_daemon.sh 8000 development
```

生产环境：
```bash
./start_api_no_build_daemon.sh 8000 production
```

**环境变量方式：**

也可以通过设置环境变量来指定运行模式：
```bash
export ENVIRONMENT=production
python api_server.py --host 0.0.0.0 --port 8000
```

#### Systemd服务

systemd服务配置文件 (`rag-api.service.example`) 默认配置为生产环境模式。

## 配置说明

编辑 `config.json` 文件以调整以下参数：

配置文件现在支持开发和生产两种环境模式，结构如下：

```json
{
  "development": {
    "embedding_model": {
      "provider": "openai",
      "model_name": "text-embedding-v4",
      "api_key": "your-dev-api-key",
      "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
      "dimension": 1024,
      "ssl_verify": true
    },
    "rerank_model": {
      "provider": "aliyun",
      "model_name": "qwen3-rerank",
      "api_key": "your-dev-api-key",
      "endpoint": "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
      "dimension": 1024,
      "ssl_verify": true
    },
    "chunking": {
      "chunk_size": 512,
      "overlap": 50
    },
    "search": {
      "top_k": 5,
      "similarity_threshold": 0.5
    },
    "vector_store_path": "./data/vector_store_text_embedding"
  },
  "production": {
    "embedding_model": {
      "provider": "openai",
      "model_name": "bge",
      "api_key": "your-prod-api-key",
      "endpoint": "https://ai-llm.nucc.com/v1/models",
      "dimension": 1024,
      "ssl_verify": false
    },
    "rerank_model": {
      "provider": "openai",
      "model_name": "bge-reranker-large",
      "api_key": "your-prod-api-key",
      "endpoint": "https://ai-llm.nucc.com/v1/models",
      "dimension": 1024,
      "ssl_verify": false
    },
    "chunking": {
      "chunk_size": 512,
      "overlap": 50
    },
    "search": {
      "top_k": 5,
      "similarity_threshold": 0.5
    },
    "vector_store_path": "./data/vector_store_text_embedding"
  },
  "default_env": "development"
}
```

- `development`: 开发环境配置
  - `embedding_model`: 嵌入模型配置
    - `api_key`: API密钥
    - `model_name`: 使用的模型名称
    - `endpoint`: API端点
    - `ssl_verify`: 是否验证SSL证书
  - `rerank_model`: 重排序模型配置
    - `api_key`: API密钥
    - `model_name`: 使用的模型名称
    - `endpoint`: API端点
    - `ssl_verify`: 是否验证SSL证书
  - `chunking`: 文档分块配置
    - `chunk_size`: 分块大小
    - `overlap`: 块间重叠大小
  - `search`: 搜索配置
    - `top_k`: 返回结果数量
    - `similarity_threshold`: 相似度阈值
  - `vector_store_path`: 向量库默认存储路径

- `production`: 生产环境配置（结构与开发环境相同）
- `default_env`: 默认环境，当未指定ENVIRONMENT环境变量时使用的环境

## 安装依赖

```bash
pip install -r requirements.txt
```
