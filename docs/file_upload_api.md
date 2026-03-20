# 文件上传API功能说明

## 概述

RAG系统现在支持通过HTTP接口直接上传文件进行处理和存储。这个新功能使得用户可以直接上传PDF、DOCX、TXT等格式的文件，而不需要预先将文件内容转换为JSON格式。

多知识域说明：
- 推荐通过 Header `X-Knowledge-Scope` 指定知识域：`audit` 或 `discipline`
- 也可通过 form/query/body 传 `scope`
- `store_path` 透传已禁用

## 新增API端点

- **端点**: `POST /upload_store`
- **功能**: 上传文件并自动处理存储
- **支持的文件格式**: PDF、DOCX、TXT
- **端点**: `POST /upload_archive_store`
- **功能**: 上传 ZIP 压缩包并自动解压、处理、存储
- **压缩包内支持格式**: PDF、DOCX、TXT

## 请求参数

### 表单数据参数

| 参数名 | 类型 | 必需 | 默认值 | 描述 |
|--------|------|------|--------|------|
| files | File[] | 是 | - | 要上传的一个或多个文件（支持中文名） |
| chunker_type | String | 否 | "smart" | 分块器类型：smart, law, audit, default |
| doc_type | String | 否 | "internal_regulation" | 文档类型：internal_regulation, external_regulation, internal_report, external_report |
| save_after_processing | String | 否 | "true" | 处理后是否自动保存向量库 |
| scope | String | 否 | default_scope | 知识域：audit 或 discipline |

### 压缩包上传参数（`POST /upload_archive_store`）

| 参数名 | 类型 | 必需 | 默认值 | 描述 |
|--------|------|------|--------|------|
| archive | File | 是 | - | ZIP 压缩包（每次上传一个类别） |
| chunker_type | String | 否 | "smart" | 分块器类型：smart, law, audit, issue, default |
| doc_type | String | 否 | "internal_regulation" | 文档类型：internal_regulation, external_regulation, internal_report, external_report, audit_issue |
| save_after_processing | String | 否 | "true" | 处理后是否自动保存向量库 |
| scope | String | 否 | default_scope | 知识域：audit 或 discipline |

## 响应格式

成功响应：

```json
{
  "success": true,
  "message": "处理完成: 新增 2 个, 跳过 1 个重复, 更新 0 个",
  "file_count": 2,
  "processed_count": 2,
  "skipped_count": 1,
  "updated_count": 0,
  "total_chunks": 18,
  "chunker_used": "smart"
}
```

压缩包上传成功响应示例：

```json
{
  "success": true,
  "message": "处理完成: 新增 5 个, 跳过 0 个重复, 更新 0 个",
  "archive_name": "external_report_2025.zip",
  "file_count": 5,
  "extracted_count": 5,
  "unsupported_files": [],
  "failed_files": [],
  "processed_count": 5,
  "skipped_count": 0,
  "updated_count": 0,
  "total_chunks": 86,
  "chunker_used": "audit_report"
}
```

说明：

- `processed_count`：本次新增入库的文档数
- `skipped_count`：因内容去重被跳过的文档数
- `updated_count`：命中已有记录并完成更新的文档数
- `total_chunks`：当前系统中累计分块总数（活跃文档）

错误响应：

```json
{
  "error": "错误消息"
}
```

## 使用示例

### cURL 示例

上传审计报告：

```bash
curl -X POST http://localhost:8000/upload_store \
  -H "X-Knowledge-Scope: audit" \
  -F "files=@/path/to/审计报告.docx" \
  -F "chunker_type=audit" \
  -F "doc_type=external_report"
```

上传法规制度：

```bash
curl -X POST http://localhost:8000/upload_store \
  -H "X-Knowledge-Scope: audit" \
  -F "files=@/path/to/管理办法.pdf" \
  -F "chunker_type=law"
```

上传压缩包：

```bash
curl -X POST http://localhost:8000/upload_archive_store \
  -H "X-Knowledge-Scope: discipline" \
  -F "archive=@/path/to/外部报告.zip" \
  -F "doc_type=external_report" \
  -F "chunker_type=audit_report"
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
headers = {
    'X-Knowledge-Scope': 'audit'
}
data = {
    'save_after_processing': 'true'
}

response = requests.post(url, files=files, data=data, headers=headers)
print(response.json())

# 记得关闭文件
for file_tuple in files:
    file_tuple[1][1].close()
```

## 技术实现

1. 文件上传：使用Flask的request.files获取上传文件或压缩包
2. 临时存储：将上传内容保存到临时目录
3. 压缩包校验：校验 ZIP 路径越界、文件数量、单文件大小、总解压大小、压缩比
4. 格式识别：仅放行 PDF、DOCX、TXT
5. 内容提取：使用document_processor.py处理不同格式文件
6. 文档去重：按文档内容计算哈希并识别重复内容
7. 文档分块：使用document_chunker.py对文档进行分块
8. 向量化：使用嵌入提供者将文本块转换为向量
9. 存储：将向量和文档信息存储到向量库，并同步写入文档元数据

## 注意事项

1. 上传文件和解压文件都会在临时目录处理，结束后自动删除
2. 压缩包只支持 ZIP，且包内只支持 PDF、DOCX、TXT
3. 大文件或大压缩包处理时间较长，请按网关超时策略配置
4. 建议按类别分包上传，避免单包过大
5. 确保服务器有足够的磁盘空间存储向量库

## 错误处理

- `400 Bad Request`: 缺少必要参数或文件
- `500 Internal Server Error`: 处理过程中出现错误
