import hashlib
import re
from typing import Any, Dict, Iterable, List, Set, Tuple

from src.indexing.graph.graph_store import GraphStore


class GraphBuilder:
    """Build a lightweight domain graph from chunked documents."""

    ISSUE_KEYWORDS = [
        "整改",
        "问题",
        "违规",
        "风险",
        "内控",
        "数据安全",
        "个人信息",
        "网络安全",
        "采购",
        "预算",
        "资金",
        "治理",
        "制度",
        "合规",
    ]

    CLAUSE_PATTERN = re.compile(r"第[一二三四五六七八九十百千万零0-9]+条")
    YEAR_PATTERN = re.compile(r"(?:19|20)\d{2}")
    DEPT_PATTERN = re.compile(r"(?:部门单位|部门)\s*[:：]\s*([^\n|]{2,60})")
    ORG_PATTERN = re.compile(r"([\u4e00-\u9fa5]{2,20}(?:部|委|局|署|司|办|院|行|公司|银行|集团))")

    def build(self, documents: Iterable[Dict[str, Any]]) -> GraphStore:
        graph = GraphStore()

        for doc in documents:
            if doc.get("status") == "deleted":
                continue

            text = str(doc.get("text", "")).strip()
            if not text:
                continue

            doc_id = str(doc.get("doc_id", ""))
            chunk_id = str(doc.get("chunk_id", ""))
            if not doc_id or not chunk_id:
                continue

            doc_node_id = f"document:{doc_id}"
            chunk_node_id = f"chunk:{chunk_id}"

            graph.add_node(
                doc_node_id,
                "document",
                doc.get("title") or doc.get("filename") or doc_id,
                attrs={
                    "doc_id": doc_id,
                    "doc_type": doc.get("doc_type", ""),
                    "filename": doc.get("filename", ""),
                },
            )

            graph.add_node(
                chunk_node_id,
                "chunk",
                chunk_id,
                attrs={
                    "chunk_id": chunk_id,
                    "doc_id": doc_id,
                    "doc_type": doc.get("doc_type", ""),
                    "filename": doc.get("filename", ""),
                    "title": doc.get("title", ""),
                    "semantic_boundary": doc.get("semantic_boundary", ""),
                    "page_nos": doc.get("page_nos", []),
                },
            )

            graph.add_edge(doc_node_id, chunk_node_id, "contains", bidirectional=True, reverse_relation="part_of")

            for ent_type, ent_value in self._extract_entities(doc):
                entity_node_id = self._entity_node_id(ent_type, ent_value)
                graph.add_node(entity_node_id, ent_type, ent_value)
                graph.add_edge(chunk_node_id, entity_node_id, "mentions", bidirectional=True, reverse_relation="mentioned_by")

        return graph

    def _extract_entities(self, doc: Dict[str, Any]) -> Set[Tuple[str, str]]:
        text = str(doc.get("text", ""))
        filename = str(doc.get("filename", ""))
        title = str(doc.get("title", ""))
        merged = f"{title}\n{filename}\n{text}"

        entities: Set[Tuple[str, str]] = set()

        doc_type = str(doc.get("doc_type", "")).strip()
        if doc_type:
            entities.add(("doc_type", doc_type))

        for year in self.YEAR_PATTERN.findall(merged):
            entities.add(("year", year))

        for clause in self.CLAUSE_PATTERN.findall(text[:6000]):
            entities.add(("clause", clause))

        for dept in self.DEPT_PATTERN.findall(text[:5000]):
            value = dept.strip()
            if value:
                entities.add(("department", value[:60]))

        if doc_type == "audit_issue":
            for org in self.ORG_PATTERN.findall(text[:5000]):
                if len(org) >= 3:
                    entities.add(("department", org[:60]))

        lowered = merged.lower()
        for kw in self.ISSUE_KEYWORDS:
            if kw.lower() in lowered:
                entities.add(("issue_topic", kw))

        header = str(doc.get("header", "")).strip()
        if header:
            entities.add(("section", header[:80]))

        level1 = str(doc.get("level1_title", "")).strip()
        if level1:
            entities.add(("section", level1[:80]))

        level2 = str(doc.get("level2_title", "")).strip()
        if level2:
            entities.add(("section", level2[:80]))

        return entities

    @staticmethod
    def _entity_node_id(entity_type: str, entity_value: str) -> str:
        raw = f"{entity_type}:{entity_value}"
        digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]
        return f"{entity_type}:{digest}"
