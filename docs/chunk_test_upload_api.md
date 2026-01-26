# 上传文件分块测试API功能说明

## 概述

RAG系统提供了专门用于上传文件并测试文档分块功能的API接口。这个接口允许您上传实际的文档文件（PDF、DOCX、TXT等格式），并测试在不同分块策略下的分块效果，预览分块结果，而无需实际存储到向量库。

## API端点

- **端点**: `POST /chunk_test_upload`
- **功能**: 上传文件并测试分块效果，返回分块结果
- **特点**: 不实际存储到向量库，仅返回分块预览

## 请求参数

### 表单数据参数

| 参数名 | 类型 | 必需 | 默认值 | 描述 |
|--------|------|------|--------|------|
| file | File | 是 | - | 要上传的文档文件，支持PDF、DOCX、TXT格式 |
| use_law_chunker | String | 否 | "false" | 是否使用法规文档分块器 |
| chunk_size | String | 否 | "512" | 分块大小 |
| overlap | String | 否 | "50" | 块间重叠大小 |

## 响应格式

成功响应：

```json
{
  "success": true,
  "filename": "company_regulations.pdf",
  "file_type": "pdf",
  "chunker_used": "law",
  "original_text_length": 2500,
  "chunks_count": 5,
  "chunks": [
    {
      "chunk_id": 1,
      "text": "第一章 总则\n第一条 为了规范...",
      "full_text_length": 520,
      "semantic_boundary": "article",
      "section_path": ["第一章 总则"],
      "header": "第一条 为了规范...",
      "char_count": 520
    },
    {
      "chunk_id": 2,
      "text": "第二条 本规定适用于...",
      "full_text_length": 480,
      "semantic_boundary": "article",
      "section_path": ["第二章 适用范围"],
      "header": "第二条 本规定适用于...",
      "char_count": 480
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

测试PDF文件的法规分块：

```bash
curl -X POST http://localhost:8000/chunk_test_upload \
  -F "file=@/path/to/company_regulations.pdf" \
  -F "use_law_chunker=true" \
  -F "chunk_size=512" \
  -F "overlap=50"
```

测试DOCX文件的标准分块：

```bash
curl -X POST http://localhost:8000/chunk_test_upload \
  -F "file=@/path/to/normal_document.docx" \
  -F "use_law_chunker=false" \
  -F "chunk_size=1024" \
  -F "overlap=100"
```

测试TXT文件并调整分块参数：

```bash
curl -X POST http://localhost:8000/chunk_test_upload \
  -F "file=@/path/to/procedure_manual.txt" \
  -F "use_law_chunker=true" \
  -F "chunk_size=300" \
  -F "overlap=30"
```

### Python 示例

```python
import requests

url = "http://localhost:8000/chunk_test_upload"

# 上传并测试PDF文件
files = {
    'file': ('company_regulations.pdf', open('/path/to/company_regulations.pdf', 'rb'), 'application/pdf')
}

data = {
    'use_law_chunker': 'true',
    'chunk_size': '512',
    'overlap': '50'
}

response = requests.post(url, files=files, data=data)
result = response.json()

print(f"文件名: {result['filename']}")
print(f"文件类型: {result['file_type']}")
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

# 记得关闭文件
files['file'][1].close()
```

## 应用场景

1. **实际文件测试**: 直接上传真实文档测试分块效果
2. **格式兼容性验证**: 验证不同文档格式的处理效果
3. **参数优化**: 针对特定文件调整最优的分块参数
4. **法规文档适配**: 测试法规文档分块器对实际法规文件的处理效果
5. **质量评估**: 预览真实文档的分块结果，确保质量满足需求

## 注意事项

1. 此接口不实际存储文档到向量库
2. 仅返回分块预览，实际处理时可能略有差异
3. 支持PDF、DOCX、TXT等常见文档格式
4. 上传的文件会在处理后自动删除
5. 对于大文件，处理可能需要一定时间
6. 推荐先使用此接口测试实际文件的分块效果，再进行正式处理