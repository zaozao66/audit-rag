# 分块测试API功能说明

## 概述

RAG系统提供了专门用于测试文档分块功能的API接口。这个接口允许您在不实际存储到向量库的情况下测试文档分块效果，预览分块结果，并比较不同分块策略的效果。

## API端点

- **端点**: `POST /chunk_test`
- **功能**: 测试文档分块效果并返回分块结果
- **特点**: 不实际存储到向量库，仅返回分块预览

## 请求参数

### JSON请求体参数

| 参数名 | 类型 | 必需 | 默认值 | 描述 |
|--------|------|------|--------|------|
| text | String | 是 | - | 要分块的文档文本内容 |
| filename | String | 否 | "test_document.txt" | 文件名标识 |
| use_law_chunker | Boolean | 否 | false | 是否使用法规文档分块器 |
| chunk_size | Integer | 否 | 512 | 分块大小 |
| overlap | Integer | 否 | 50 | 块间重叠大小 |

## 响应格式

成功响应：

```json
{
  "success": true,
  "chunker_used": "law",
  "original_text_length": 1250,
  "chunks_count": 3,
  "chunks": [
    {
      "chunk_id": 1,
      "text": "第一章 总则\n第一条 为了规范...",
      "full_text_length": 420,
      "semantic_boundary": "article",
      "section_path": ["第一章 总则"],
      "header": "第一条 为了规范...",
      "char_count": 420
    },
    {
      "chunk_id": 2,
      "text": "第二条 本规定适用于...",
      "full_text_length": 380,
      "semantic_boundary": "article",
      "section_path": ["第二章 适用范围"],
      "header": "第二条 本规定适用于...",
      "char_count": 380
    },
    {
      "chunk_id": 3,
      "text": "第三条 公司应当遵守...",
      "full_text_length": 450,
      "semantic_boundary": "article",
      "section_path": ["第一章 总则"],
      "header": "第三条 公司应当遵守...",
      "char_count": 450
    }
  ]
}
```

错误响应：

```json
{
  "error": "错误消息"
}
```

## 使用示例

### cURL 示例

测试法规文档分块：

```bash
curl -X POST http://localhost:8000/chunk_test \
  -H "Content-Type: application/json" \
  -d '{
    "text": "第一章 总则\n第一条 为了规范企业行为...\n第二条 本规定适用于...",
    "filename": "regulations.txt",
    "use_law_chunker": true,
    "chunk_size": 512,
    "overlap": 50
  }'
```

测试标准文档分块：

```bash
curl -X POST http://localhost:8000/chunk_test \
  -H "Content-Type: application/json" \
  -d '{
    "text": "这是普通的文档内容，将按照常规方式进行分块...",
    "filename": "normal_doc.txt",
    "use_law_chunker": false,
    "chunk_size": 1024,
    "overlap": 100
  }'
```

### Python 示例

```python
import requests
import json

url = "http://localhost:8000/chunk_test"

# 测试法规文档分块
payload = {
    "text": """第一章 总则
第一条 为了规范企业行为，保护公司利益，根据国家相关法律法规，制定本规定。
第二条 本规定适用于公司内所有部门及员工。
第三条 公司应当遵守国家法律法规，诚信经营，接受社会监督。

第二章 员工行为规范
第四条 员工应当遵守公司各项规章制度，维护公司形象和利益。
""",
    "filename": "company_regulations.txt",
    "use_law_chunker": True,
    "chunk_size": 512,
    "overlap": 50
}

headers = {
    'Content-Type': 'application/json'
}

response = requests.post(url, headers=headers, json=payload)
result = response.json()

print(f"使用分块器: {result['chunker_used']}")
print(f"原文长度: {result['original_text_length']}")
print(f"分块数量: {result['chunks_count']}")

for chunk in result['chunks']:
    print(f"\n块 {chunk['chunk_id']}:")
    print(f"  类型: {chunk['semantic_boundary']}")
    print(f"  长度: {chunk['full_text_length']}")
    print(f"  预览: {chunk['text'][:100]}...")
    if chunk['section_path']:
        print(f"  章节路径: {' -> '.join(chunk['section_path'])}")
```

## 应用场景

1. **分块策略验证**: 在正式处理文档前验证分块效果
2. **参数调优**: 测试不同chunk_size和overlap参数的效果
3. **法规文档适配**: 验证法规文档分块器对特定文档的处理效果
4. **质量评估**: 预览分块结果，确保分块质量满足需求

## 注意事项

1. 此接口不实际存储文档到向量库
2. 仅返回分块预览，实际处理时可能略有差异
3. 对于大文档，返回的文本预览会截取前200个字符
4. 推荐先使用此接口测试分块效果，再进行正式处理