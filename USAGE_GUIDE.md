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
- `chunk_size`: (可选) 分块大小，默认为512
- `overlap`: (可选) 块间重叠大小，默认为50

返回结果包含分块的数量、每个块的预览以及分块详情。


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
- `chunk_size`: (可选) 分块大小，默认为512
- `overlap`: (可选) 块间重叠大小，默认为50

返回结果包含文件信息、分块的数量、每个块的预览以及分块详情。

#### 搜索文档API

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "搜索关键词",
    "top_k": 5
  }'
```

#### 清空向量库API

```bash
curl -X POST http://localhost:8000/clear
```

## 配置说明

编辑 `config.json` 文件以调整以下参数：

- `embedding_model`: 嵌入模型配置
  - `api_key`: API密钥
  - `model_name`: 使用的模型名称
  - `endpoint`: API端点
- `chunking`: 文档分块配置
  - `chunk_size`: 分块大小
  - `overlap`: 块间重叠大小
- `search`: 搜索配置
  - `top_k`: 返回结果数量
  - `similarity_threshold`: 相似度阈值
- `vector_store_path`: 向量库默认存储路径

## 安装依赖

```bash
pip install -r requirements.txt
```