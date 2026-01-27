# 重排序（Rerank）功能说明

## 概述

RAG系统集成了重排序功能，通过调用阿里云的重排序模型，对初始检索结果进行二次排序，以提升搜索结果的相关性和准确性。

## 功能特点

1. **双重排序机制**：结合向量相似度和语义重排序
2. **阿里云模型支持**：使用阿里云DashScope的gte-rerank模型
3. **灵活配置**：支持配置重排序参数
4. **兼容性**：与现有搜索功能无缝集成

## 技术原理

1. **初始检索**：使用向量相似度检索相关文档
2. **候选集合**：获取top-k的候选文档
3. **重排序**：使用阿里云重排序模型对候选文档进行语义相关性评分
4. **最终排序**：根据重排序分数返回最终结果

## API接口

### `/search_rerank` 接口

- **端点**: `POST /search_rerank`
- **功能**: 搜索文档并进行重排序
- **请求格式**: JSON
- **返回格式**: JSON

#### 请求参数

| 参数名 | 类型 | 必需 | 默认值 | 描述 |
|--------|------|------|--------|------|
| query | String | 是 | - | 搜索查询文本 |
| top_k | Integer | 否 | 5 | 返回前k个结果 |
| rerank_top_k | Integer | 否 | 10 | 重排序时考虑的文档数量 |

#### 响应格式

```json
{
  "success": true,
  "query": "搜索关键词",
  "with_rerank": true,
  "count": 5,
  "results": [
    {
      "score": 0.95,
      "original_score": 0.78,
      "text": "文档内容...",
      "doc_id": "文档ID",
      "filename": "文件名",
      "file_type": "文件类型"
    }
  ]
}
```

## 配置说明

### 配置文件

在 `config.json` 中配置重排序模型参数：

```json
{
  "rerank_model": {
    "provider": "aliyun",
    "model_name": "gte-rerank",
    "api_key": "your-api-key-here",
    "endpoint": "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-retrieve-rerank",
    "dimension": 1024
  }
}
```

### 参数说明

- `api_key`: 阿里云API密钥
- `model_name`: 重排序模型名称
- `endpoint`: API端点
- `provider`: 服务提供商

## 使用示例

### cURL示例

```bash
curl -X POST http://localhost:8000/search_rerank \
  -H "Content-Type: application/json" \
  -d '{
    "query": "公司员工行为准则",
    "top_k": 5,
    "rerank_top_k": 10
  }'
```

### Python示例

```python
import requests

url = "http://localhost:8000/search_rerank"

payload = {
    "query": "公司员工行为准则",
    "top_k": 5,
    "rerank_top_k": 10
}

headers = {
    'Content-Type': 'application/json'
}

response = requests.post(url, headers=headers, json=payload)
result = response.json()

print(f"查询: {result['query']}")
print(f"结果数量: {result['count']}")

for i, item in enumerate(result['results']):
    print(f"结果 {i+1}: 相关性分数={item['score']:.4f}")
    print(f"  内容: {item['text'][:100]}...")
```

## 与普通搜索的区别

| 特性 | 普通搜索 `/search` | 重排序搜索 `/search_rerank` |
|------|-------------------|---------------------------|
| 排序方式 | 向量相似度 | 语义相关性重排序 |
| 准确性 | 中等 | 更高 |
| 响应时间 | 较快 | 稍慢（因额外API调用） |
| API依赖 | 仅向量模型 | 向量模型 + 重排序模型 |

## 注意事项

1. **API密钥**：需要有效的阿里云重排序API密钥
2. **费用**：调用重排序API会产生费用
3. **性能**：重排序会增加响应时间
4. **回退机制**：如果重排序服务不可用，系统会自动回退到普通搜索

## 应用场景

1. **精准搜索**：需要更高搜索准确性的场景
2. **复杂查询**：处理复杂的语义查询
3. **关键应用**：对搜索结果质量要求高的应用