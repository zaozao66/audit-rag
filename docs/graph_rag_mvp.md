# GraphRAG MVP 使用说明

## 目标

在现有 VectorRAG 基础上增加图检索能力，支持：
- 多跳关联召回（法规-问题-整改-部门）
- `vector / graph / hybrid` 三种检索模式
- 检索分数拆分（`vector_score` + `graph_score`）

## 已实现内容

- 图存储与查询：`src/indexing/graph/graph_store.py`
- 图构建器：`src/indexing/graph/graph_builder.py`
- 图检索器：`src/indexing/graph/graph_retriever.py`
- 检索融合入口：`src/retrieval/router/rag_processor.py`
- API 参数扩展：`/search_with_intent`、`/ask`、`/v1/chat/completions`
- 图索引重建接口：`POST /graph/rebuild`

## 检索模式

### 1) 仅向量检索（默认）

```json
{
  "retrieval_mode": "vector"
}
```

### 2) 仅图检索

```json
{
  "retrieval_mode": "graph",
  "graph_hops": 2
}
```

### 3) 混合检索（推荐）

```json
{
  "retrieval_mode": "hybrid",
  "graph_hops": 2,
  "hybrid_alpha": 0.65
}
```

说明：
- `hybrid_alpha` 越大越偏向向量检索（范围 0~1）
- `graph_hops` 为图扩展跳数，建议 1~3

## 运维流程

1. 上传/入库文档（会自动构建图索引）
2. 当你批量替换了底层 `.docs/.index` 文件时，手动调用：

```bash
curl -X POST http://localhost:8000/graph/rebuild
```

3. 查看系统信息：

```bash
curl http://localhost:8000/info
```

返回中 `graph` 字段可看到图索引状态。

## 数据质量建议

- 推荐重新入库一次历史数据，确保每个 chunk 拥有稳定 `chunk_id`。
- PDF 已注入页码标记并在入库时清洗为 `page_nos`，建议用新流程再跑一遍关键资料。
- 当前图实体以规则抽取为主（条款、年份、部门、问题主题、章节），后续可叠加 LLM 抽取增强精度。

## 后续增强建议

- 增加图路径解释（返回命中路径）
- 引入图节点类型权重（法规条款 > 主题词）
- 增加离线评测集并统计 Recall@K / MRR / 引用完整率
