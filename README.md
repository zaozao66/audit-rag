# 阿里云Text Embedding RAG系统

本项目实现了使用阿里云text-embedding-v4模型的RAG（检索增强生成）系统，通过OpenAI SDK调用API进行向量嵌入。

## 功能特点

- ✅ 使用阿里云text-embedding-v4模型进行向量嵌入
- ✅ 支持用户上传PDF、DOCX、TXT格式文档
- ✅ 自动文档分块处理
- ✅ 高效向量相似性搜索（基于Faiss）
- ✅ 支持向量库持久化存储

## 技术架构

- **嵌入模型**: 阿里云text-embedding-v4（1024维向量）
- **向量库**: Faiss（高效相似性搜索）
- **文档处理**: 支持PDF、DOCX、TXT格式
- **API调用**: 通过OpenAI SDK调用阿里云兼容模式API

## 文件说明

- `full_aliyun_rag_system.py` - 主RAG系统入口
- `aliyun_rag_system.py` - 核心RAG处理逻辑
- `document_processor.py` - 文档格式处理
- `config.json` - 系统配置文件
- `requirements.txt` - 项目依赖

## 使用方法

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 运行系统

```bash
# 运行系统（使用示例文档）
python3 full_aliyun_rag_system.py

# 或者处理用户上传的文档
python3 full_aliyun_rag_system.py /path/to/document1.pdf /path/to/document2.docx
```

### 3. 配置说明

在 `config.json` 中可以配置：

```json
{
  "embedding_model": {
    "provider": "openai",
    "model_name": "text-embedding-v4",
    "api_key": "your-api-key",
    "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "dimension": 1024
  },
  "chunking": {
    "chunk_size": 512,
    "overlap": 50
  },
  "search": {
    "top_k": 5,
    "similarity_threshold": 0.5
  }
}
```

## 系统流程

1. **文档上传与解析**: 支持PDF、DOCX、TXT格式文档
2. **文档分块**: 将长文档分割为固定大小的块
3. **向量嵌入**: 通过阿里云API生成文档块的向量表示
4. **向量存储**: 使用Faiss向量库存储向量和文档映射关系
5. **相似性搜索**: 根据查询找到最相关的文档块

## API配置

系统使用阿里云DashScope的兼容OpenAI API模式，endpoint为：
`https://dashscope.aliyuncs.com/compatible-mode/v1`

## 性能优化

- 文档自动分块，适应模型输入限制
- 使用Faiss进行高效向量相似性搜索
- 支持向量库持久化，避免重复处理

## 注意事项

- 需要有效阿里云API密钥才能调用embedding服务
- 每次调用API会产生费用，请注意控制使用量
- 文档处理支持中文内容