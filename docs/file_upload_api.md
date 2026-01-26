# 文件上传API功能说明

## 概述

RAG系统现在支持通过HTTP接口直接上传文件进行处理和存储。这个新功能使得用户可以直接上传PDF、DOCX、TXT等格式的文件，而不需要预先将文件内容转换为JSON格式。

## 新增API端点

- **端点**: `POST /upload_store`
- **功能**: 上传文件并自动处理存储
- **支持的文件格式**: PDF、DOCX、TXT

## 请求参数

### 表单数据参数

| 参数名 | 类型 | 必需 | 默认值 | 描述 |
|--------|------|------|--------|------|
| files | File[] | 是 | - | 要上传的一个或多个文件 |
| save_after_processing | String | 否 | "true" | 处理后是否自动保存向量库 |
| store_path | String | 否 | - | 自定义向量库存储路径 |

## 响应格式

成功响应：

```json
{
  "success": true,
  "message": "成功处理了 2 个文件，生成了 5 个文本块",
  "file_count": 2,
  "processed_count": 5
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

上传单个文件：

```bash
curl -X POST http://localhost:8000/upload_store \
  -F "files=@/path/to/document.pdf" \
  -F "save_after_processing=true"
```

上传多个文件：

```bash
curl -X POST http://localhost:8000/upload_store \
  -F "files=@/path/to/document1.pdf" \
  -F "files=@/path/to/document2.docx" \
  -F "files=@/path/to/document3.txt" \
  -F "store_path=./my_custom_store"
```

### Python 示例

```python
import requests

url = "http://localhost:8000/upload_store"

# 准备要上传的文件
files = [
    ('files', ('document1.pdf', open('/path/to/document1.pdf', 'rb'), 'application/pdf')),
    ('files', ('document2.docx', open('/path/to/document2.docx', 'rb'), 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')),
]

# 可选参数
data = {
    'save_after_processing': 'true',
    'store_path': './my_custom_store'
}

response = requests.post(url, files=files, data=data)
print(response.json())

# 记得关闭文件
for file_tuple in files:
    file_tuple[1][1].close()
```

## 技术实现

1. 文件上传：使用Flask的request.files获取上传的文件
2. 临时存储：将上传的文件保存到临时位置
3. 格式识别：根据文件扩展名识别文件类型
4. 内容提取：使用document_processor.py处理不同格式的文件
5. 文档分块：使用document_chunker.py对文档进行分块
6. 向量化：使用嵌入提供者将文本块转换为向量
7. 存储：将向量和文档信息存储到向量库

## 注意事项

1. 上传的文件会被临时存储在系统临时目录中，处理完成后自动删除
2. 大文件可能需要较长时间处理，请耐心等待响应
3. 一次请求可以上传多个文件，但建议控制文件总数以避免内存问题
4. 确保服务器有足够的磁盘空间存储向量库

## 错误处理

- `400 Bad Request`: 缺少必要参数或文件
- `500 Internal Server Error`: 处理过程中出现错误