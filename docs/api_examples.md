# HTTP API 使用示例

本文档提供RAG系统HTTP API的各种使用示例。

## 启动API服务器

```bash
# 使用默认端口8000启动
./start_api.sh

# 或指定端口启动
./start_api.sh 9000
```

## API端点列表

- `GET  /health` - 健康检查
- `POST /store` - 存储文档
- `POST /upload_store` - 文件上传并入库
- `POST /search` - 搜索文档
- `POST /clear` - 清空向量库
- `GET  /info` - 系统信息
- `GET  /documents` - 文档列表
- `GET  /documents/<doc_id>` - 文档详情
- `DELETE /documents/<doc_id>` - 删除文档
- `GET  /documents/<doc_id>/chunks` - 文档分块
- `GET  /documents/stats` - 文档统计

## 详细使用示例

### 1. 健康检查

```bash
curl -X GET http://localhost:8000/health
```

响应示例：
```json
{
  "status": "healthy",
  "message": "RAG系统HTTP API服务运行正常"
}
```

### 2. 存储文档

#### 基本存储

```bash
curl -X POST http://localhost:8000/store \
  -H "Content-Type: application/json" \
  -d '{
    "documents": [
      {
        "doc_id": "doc_1",
        "title": "人工智能介绍",
        "text": "人工智能（Artificial Intelligence，AI）是计算机科学的一个分支，它企图了解智能的实质，并生产出一种新的能以人类智能相似的方式做出反应的智能机器。",
        "source": "example_1"
      },
      {
        "doc_id": "doc_2", 
        "title": "机器学习概念",
        "text": "机器学习是人工智能的一个子领域，它使计算机能够在没有明确编程的情况下学习。机器学习算法构建数学模型，依据经验数据来进行预测或决策。",
        "source": "example_2"
      }
    ]
  }'
```

响应示例：
```json
{
  "success": true,
  "message": "成功处理了 2 个文本块",
  "processed_count": 2
}
```

#### 指定自定义存储路径

```bash
curl -X POST http://localhost:8000/store \
  -H "Content-Type: application/json" \
  -d '{
    "documents": [
      {
        "doc_id": "doc_3",
        "text": "这是另一个文档的内容..."
      }
    ],
    "store_path": "./data/my_custom_store"
  }'
```

### 3. 搜索文档

#### 基本搜索

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "什么是人工智能",
    "top_k": 3
  }'
```

响应示例：
```json
{
  "success": true,
  "query": "什么是人工智能",
  "results": [
    {
      "score": 0.8542,
      "text": "人工智能（Artificial Intelligence，AI）是计算机科学的一个分支，它企图了解智能的实质，并生产出一种新的能以人类智能相似的方式做出反应的智能机器。",
      "doc_id": "doc_1",
      "filename": "",
      "file_type": ""
    }
  ],
  "count": 1
}
```

#### 指定自定义存储路径搜索

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "机器学习",
    "top_k": 5,
    "store_path": "./data/my_custom_store"
  }'
```

### 4. 清空向量库

```bash
curl -X POST http://localhost:8000/clear
```

响应示例：
```json
{
  "success": true,
  "message": "向量库已清空并保存"
}
```

#### 指定自定义存储路径清空

```bash
curl -X POST http://localhost:8000/clear \
  -H "Content-Type: application/json" \
  -d '{
    "store_path": "./data/my_custom_store"
  }'
```

### 5. 获取系统信息

```bash
curl -X GET http://localhost:8000/info
```

响应示例：
```json
{
  "status": "running",
  "vector_store_status": "loaded",
  "vector_count": 10,
  "dimension": 1024,
  "document_stats": {
    "total_documents": 12,
    "active_documents": 10,
    "deleted_documents": 2,
    "total_chunks": 268,
    "total_size_bytes": 1532456,
    "total_size_mb": 1.46,
    "by_type": {
      "internal_regulation": {
        "count": 6,
        "chunks": 180
      },
      "external_report": {
        "count": 4,
        "chunks": 88
      }
    }
  }
}
```

### 6. 上传文件并入库（带去重统计）

```bash
curl -X POST http://localhost:8000/upload_store \
  -F "files=@/path/to/审计报告.docx" \
  -F "files=@/path/to/制度汇编.pdf" \
  -F "chunker_type=smart" \
  -F "doc_type=internal_regulation"
```

响应示例：
```json
{
  "success": true,
  "message": "处理完成: 新增 2 个, 跳过 1 个重复, 更新 0 个",
  "file_count": 3,
  "processed_count": 2,
  "skipped_count": 1,
  "updated_count": 0,
  "total_chunks": 268,
  "chunker_used": "smart"
}
```

### 7. 获取文档列表

```bash
curl -X GET "http://localhost:8000/documents?doc_type=internal_regulation&keyword=制度&include_deleted=false"
```

### 8. 获取单个文档详情

```bash
curl -X GET http://localhost:8000/documents/2f6ab1d2f10c1f8a
```

### 9. 获取文档分块

```bash
curl -X GET "http://localhost:8000/documents/2f6ab1d2f10c1f8a/chunks?include_text=false"
```

### 10. 删除文档

```bash
curl -X DELETE http://localhost:8000/documents/2f6ab1d2f10c1f8a
```

### 11. 获取文档统计

```bash
curl -X GET http://localhost:8000/documents/stats
```

## 错误处理

API在遇到错误时会返回适当的HTTP状态码和错误信息：

- `400 Bad Request`: 请求格式错误或缺少必要参数
- `404 Not Found`: 向量库不存在
- `500 Internal Server Error`: 服务器内部错误

错误响应格式：
```json
{
  "error": "错误描述信息"
}
```

## 注意事项

1. 所有POST请求都需要包含 `Content-Type: application/json` 头部
2. 文档文本应避免过长，建议单个文档不超过一定字符限制
3. 搜索的 `top_k` 参数控制返回结果数量，默认为5
4. API服务器默认监听在 `0.0.0.0:8000`
