# RAG系统

这是一个基于文本嵌入API的RAG（检索增强生成）系统，能够处理PDF、DOCX和TXT格式的文档，并将其转换为向量存储在Faiss索引中，以支持语义搜索。

## 功能特性

- 支持PDF、DOCX和TXT格式文档处理
- 使用text-embedding-v4模型生成文档向量
- 使用Faiss进行高效的向量相似性搜索
- 支持中文文档处理
- 可配置的文档分块策略
- **独立的存储和搜索功能**：支持独立的存储和搜索命令
- **多文件支持**：支持同时处理多个文档
- **持久化向量库**：支持向量库的保存和加载，实现跨会话使用
- **HTTP API接口**：支持通过HTTP请求进行存储、搜索和清除操作
- **灵活的命令行接口**：清晰的命令行界面

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

### 命令行接口

#### 存储文档到向量库

```bash
# 存储单个或多个文档
python main.py store --files /path/to/doc1.pdf /path/to/doc2.docx

# 指定自定义向量库存储路径
python main.py store --files /path/to/doc1.pdf --store-path ./my_custom_store
```

#### 搜索文档

```bash
# 直接搜索
python main.py search --query "你的查询内容"

# 交互式搜索（可连续提问）
python main.py search

# 指定自定义向量库路径
python main.py search --query "查询内容" --store-path ./my_custom_store
```

#### 清空向量库

```bash
# 清空向量库
python main.py clear
```

### HTTP API接口

启动HTTP API服务器：

```bash
# 默认端口8000
./start_api.sh

# 或指定端口
./start_api.sh 9000
```

API端点：

- `GET  /health` - 健康检查
- `POST /store` - 存储文档
- `POST /search` - 搜索文档
- `POST /clear` - 清空向量库
- `GET  /info` - 系统信息

#### 存储文档API示例：

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

#### 搜索文档API示例：

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "搜索关键词",
    "top_k": 5
  }'
```

#### 清空向量库API示例：

```bash
curl -X POST http://localhost:8000/clear
```

## 项目结构

```
audit-rag/
├── main.py                 # 主程序入口（命令行接口）
├── api_server.py           # HTTP API服务器
├── cli_app.py              # 命令行接口应用程序
├── config.json             # 配置文件
├── requirements.txt        # 依赖包列表
├── README.md               # 项目说明
├── USAGE_GUIDE.md          # 详细使用说明
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
└── data/                   # 数据目录
    └── vector_store_text_embedding.*  # 向量库文件
```

## 技术架构

- 文档处理：支持PDF（pdfplumber）、DOCX（python-docx）、TXT（内置）格式
- 文档分块：基于语义边界的智能分块算法
- 嵌入模型：text-embedding-v4
- 向量存储：Faiss索引，支持持久化
- 搜索算法：余弦相似度匹配
- 命令行接口：支持独立的存储和搜索功能
- HTTP API：Flask Web服务，支持RESTful接口