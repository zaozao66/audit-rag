# RAG系统使用说明

## 项目结构

```
audit-rag/
├── main.py                 # 主程序入口（命令行接口）
├── api_server.py           # HTTP API服务器
├── cli_app.py              # 命令行接口应用程序
├── config.json             # 配置文件
├── requirements.txt        # 依赖包列表
├── README.md               # 项目说明
├── USAGE_GUIDE.md          # 本文件
├── start.sh                # 命令行启动脚本
├── start_api.sh            # HTTP API启动脚本
├── src/                    # 源代码目录
│   ├── __init__.py
│   ├── config_loader.py    # 配置加载
│   ├── document_chunker.py # 文档分块处理
│   ├── document_processor.py # 文档格式处理
│   ├── embedding_providers.py # 嵌入模型提供者
│   ├── rag_processor.py    # RAG处理主逻辑
│   └── vector_store.py     # 向量存储
├── data/                   # 数据目录
│   └── vector_store_text_embedding.*  # 向量库文件
└── docs/                   # 文档目录
```

## 功能特性

1. **文档存储**：将文档内容转换为向量并存储到向量数据库
2. **文档搜索**：通过语义相似性搜索相关文档片段
3. **多文件支持**：支持同时处理多个文档
4. **持久化存储**：向量库可保存和加载，支持跨会话使用
5. **HTTP API接口**：支持通过HTTP请求进行存储、搜索和清除操作

## 使用方法

### 1. 命令行接口

#### 存储文档

将文档存储到向量库：

```bash
python main.py store --files /path/to/doc1.pdf /path/to/doc2.docx /path/to/doc3.txt
```

指定自定义向量库存储路径：

```bash
python main.py store --files /path/to/doc1.pdf --store-path ./my_custom_store
```

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

- `GET  /health` - 健康检查
- `POST /store` - 存储文档(JSON格式)
- `POST /upload_store` - 上传并存储文档(文件上传)
- `POST /chunk_test` - 测试文档分块功能(文本输入)
- `POST /chunk_test_upload` - 测试文档分块功能(文件上传)
- `POST /search` - 搜索文档
- `POST /search_rerank` - 搜索文档并重排序
- `POST /clear` - 清空向量库
- `GET  /info` - 系统信息

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
    ]
  }'
```

#### 上传并存储文档API (新功能)

支持直接上传文件进行存储，支持PDF、DOCX、TXT等格式：

```bash
curl -X POST http://localhost:8000/upload_store \
  -F "files=@/path/to/document1.pdf" \
  -F "files=@/path/to/document2.docx" \
  -F "files=@/path/to/document3.txt" \
  -F "save_after_processing=true" \
  -F "store_path=./custom_vector_store"
```

参数说明：
- `files`: 要上传的一个或多个文件
- `save_after_processing`: (可选) 处理后是否自动保存，默认为true
- `store_path`: (可选) 自定义向量库存储路径
- `use_law_chunker`: (可选) 是否使用法规文档分块器，默认为false
  - 法规分块器会智能识别法规文档的层级结构，将子条款（如（一）、（二）、（三）等）与上级条款合并，而不是单独切分


#### 测试文档分块API

用于测试分块效果，不实际存储到向量库：

```bash
curl -X POST http://localhost:8000/chunk_test \
  -H "Content-Type: application/json" \
  -d '{
    "text": "这里是需要分块的文档内容...",
    "filename": "test_doc.txt",
    "use_law_chunker": true,
    "chunk_size": 512,
    "overlap": 50
  }'
```

参数说明：
- `text`: (必需) 要分块的文档文本内容
- `filename`: (可选) 文件名，默认为 "test_document.txt"
- `use_law_chunker`: (可选) 是否使用法规文档分块器，默认为false
  - 法规分块器会智能识别法规文档的层级结构，将子条款（如（一）、（二）、（三）等）与上级条款合并，而不是单独切分
- `chunk_size`: (可选) 分块大小，默认为512
- `overlap`: (可选) 块间重叠大小，默认为50

返回结果包含分块的数量、每个块的预览以及分块详情.


#### 上传文件测试文档分块API

用于上传文件并测试分块效果，不实际存储到向量库：

```bash
curl -X POST http://localhost:8000/chunk_test_upload \
  -F "file=@/path/to/document.pdf" \
  -F "use_law_chunker=true" \
  -F "chunk_size=512" \
  -F "overlap=50"
```

参数说明：
- `file`: (必需) 要上传的文件（支持PDF、DOCX、TXT格式）
- `use_law_chunker`: (可选) 是否使用法规文档分块器，默认为false
  - 法规分块器会智能识别法规文档的层级结构，将子条款（如（一）、（二）、（三）等）与上级条款合并，而不是单独切分
- `chunk_size`: (可选) 分块大小，默认为512
- `overlap`: (可选) 块间重叠大小，默认为50

返回结果包含文件信息、分块的数量、每个块的预览以及分块详情.

#### 搜索文档API

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "搜索关键词",
    "top_k": 5
  }'
```

#### 带重排序的搜索文档API

使用阿里云重排序模型对搜索结果进行二次排序，提升相关性：

```bash
curl -X POST http://localhost:8000/search_rerank \
  -H "Content-Type: application/json" \
  -d '{
    "query": "搜索关键词",
    "top_k": 5,
    "rerank_top_k": 10
  }'
```

参数说明：
- `query`: (必需) 搜索查询文本
- `top_k`: (可选) 返回前k个结果，默认为5
- `rerank_top_k`: (可选) 重排序时考虑的文档数量，默认为10

#### 清空向量库API

```bash
curl -X POST http://localhost:8000/clear
```

### 3. Linux服务器部署

系统支持在Linux服务器上后台运行，便于长期部署。

#### 后台运行模式

启动后台服务（默认端口8000）：

```bash
# 启动后台服务
./start_daemon.sh

# 指定端口启动后台服务
./start_daemon.sh 9000
```

停止后台服务：

```bash
./stop_daemon.sh
```

重启后台服务：

```bash
# 重启服务（使用默认端口）
./restart_daemon.sh

# 重启服务（指定端口）
./restart_daemon.sh 9000
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
- 自动将日志输出到 `logs/api_server.log` 文件
- 使用PID文件跟踪进程状态，防止重复启动
- 支持优雅启动和停止
- 提供重启脚本便于维护

#### 使用 systemd 部署 (推荐用于生产环境)

对于Linux服务器，推荐使用systemd服务进行部署，这种方式更稳定可靠。

##### 方法一：使用自动化部署脚本（推荐）

系统提供了一个自动化部署脚本，可以一键完成所有部署步骤：

```bash
# 查看使用帮助
./deploy.sh --help

# 基本部署（使用默认设置）
./deploy.sh

# 指定安装目录和端口
./deploy.sh --dir /opt/audit-rag --port 8080

# 仅部署代码，不安装systemd服务
./deploy.sh --no-service
```

部署脚本会自动：
- 复制所有必要文件到目标目录
- 安装Python依赖
- 配置systemd服务（如果未指定--no-service）
- 设置开机自启
- 启动服务

##### 方法二：手动部署

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

## 开发与生产环境模式

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
./start_daemon.sh 8000 development
```

生产环境：
```bash
./start_daemon.sh 8000 production
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