# RAG系统

这是一个基于文本嵌入API的RAG（检索增强生成）系统，能够处理PDF、DOCX和TXT格式的文档，并将其转换为向量存储在Faiss索引中，以支持语义搜索。

## 功能特性

- 支持PDF、DOCX和TXT格式文档处理
- 使用text-embedding-v4模型生成文档向量
- 使用Faiss进行高效的向量相似性搜索
- 支持中文文档处理
- 可配置的文档分块策略
- **意图驱动搜索**：识别用户意图并动态路由至不同库（制度/报告/问题库）
- **重排序增强**：集成rerank模型提升相关性
- **LLM智能问答**：基于意图识别和检索结果生成精准回答
- **持久化向量库**：支持增量上传与自动加载
- **HTTP API接口**：提供现代化的RESTful API，支持智能问答与搜索

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
- `POST /upload_store` - (推荐) 上传并存储文档(文件)
- `POST /search_with_intent` - (推荐) 意图识别智能搜索
- `POST /ask` - 意图驱动LLM问答
- `POST /clear` - 清空向量库
- `GET  /info` - 系统信息
- `GET  /documents` - 文档列表（支持类型/关键字/是否含已删除过滤）
- `GET  /documents/<doc_id>` - 文档详情
- `DELETE /documents/<doc_id>` - 删除文档
- `GET  /documents/<doc_id>/chunks` - 文档分块详情
- `GET  /documents/stats` - 文档统计

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

#### 智能搜索API示例：

```bash
curl -X POST http://localhost:8000/search_with_intent \
  -H "Content-Type: application/json" \
  -d '{"query": "采购管理有哪些制度要求？"}'
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
├── win_manage.bat          # Windows 服务管理脚本
├── deploy.sh               # 自动化部署脚本
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

## 技术架构

- **文档处理**：支持 PDF（含表格逻辑聚合）、DOCX、TXT 格式解析
- **分块策略**：基于语义边界的智能分块，内置制度（章/节/条）、报告（一/（一））、审计台账（逻辑行）等专项优化
- **嵌入模型**：厂商中立设计，支持 text-embedding-v4、BGE 等多种 Embedding 模型
- **向量存储**：基于 Faiss 的高效向量检索，支持元数据过滤与持久化
- **检索增强**：集成意图路由 (Intent Routing) 与多级重排序 (Rerank) 机制
- **接口规范**：提供 RESTful 标准接口，并兼容 OpenAI Chat Completions 协议（支持流式响应）
