import hashlib
from typing import Any, Dict, Iterable, List, Set, Tuple

import src.indexing.graph.ontology as ontology
from src.indexing.graph.entity_linker import EntityLinker
from src.indexing.graph.extractors import (
    AuditIssueExtractor,
    AuditReportExtractor,
    BaseExtractor,
    RegulationExtractor,
    RelationRecord,
)
from src.indexing.graph.graph_store import GraphStore


class GraphBuilder:
    """Build domain graph from chunked documents using doc-type specific extractors."""

    def __init__(self):
        self.linker = EntityLinker()
        self._default_extractor = BaseExtractor()
        self._audit_issue_extractor = AuditIssueExtractor()
        self._audit_report_extractor = AuditReportExtractor()
        self._regulation_extractor = RegulationExtractor()

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

            doc_node_id = f"{ontology.ENTITY_DOCUMENT}:{doc_id}"
            chunk_node_id = f"{ontology.ENTITY_CHUNK}:{chunk_id}"

            graph.add_node(
                doc_node_id,
                ontology.ENTITY_DOCUMENT,
                doc.get("title") or doc.get("filename") or doc_id,
                attrs={
                    "doc_id": doc_id,
                    "doc_type": doc.get("doc_type", ""),
                    "filename": doc.get("filename", ""),
                },
            )

            graph.add_node(
                chunk_node_id,
                ontology.ENTITY_CHUNK,
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

            graph.add_edge(
                doc_node_id,
                chunk_node_id,
                ontology.REL_CONTAINS,
                bidirectional=True,
                reverse_relation=ontology.REL_PART_OF,
                attrs={
                    "confidence": 1.0,
                    "source_chunk_id": chunk_id,
                    "doc_id": doc_id,
                    "extractor": "graph_builder",
                },
            )

            entities = self._extract_entities(doc)
            relations = self._extract_relations(doc)

            entity_key_to_node: Dict[Tuple[str, str], str] = {}
            for entity_type, raw_value in entities:
                normalized_value = self.linker.normalize(entity_type, raw_value)
                if not normalized_value:
                    continue

                entity_key = (entity_type, normalized_value)
                entity_node_id = self._entity_node_id(entity_type, normalized_value)
                entity_key_to_node[entity_key] = entity_node_id

                graph.add_node(entity_node_id, entity_type, normalized_value)
                graph.add_edge(
                    chunk_node_id,
                    entity_node_id,
                    ontology.REL_MENTIONS,
                    bidirectional=True,
                    reverse_relation=ontology.REL_MENTIONED_BY,
                    attrs={
                        "confidence": 0.7,
                        "source_chunk_id": chunk_id,
                        "doc_id": doc_id,
                        "extractor": "entity_mention",
                    },
                )

            for record in relations:
                self._add_relation_edge(graph, record, entity_key_to_node, doc_id, chunk_id)

        return graph

    def _select_extractor(self, doc: Dict[str, Any]) -> BaseExtractor:
        doc_type = str(doc.get("doc_type", "")).lower()

        if doc_type == "audit_issue":
            return self._audit_issue_extractor
        if doc_type in ("internal_report", "external_report"):
            return self._audit_report_extractor
        if doc_type in ("internal_regulation", "external_regulation"):
            return self._regulation_extractor
        return self._default_extractor

    def _extract_entities(self, doc: Dict[str, Any]) -> Set[Tuple[str, str]]:
        extractor = self._select_extractor(doc)
        return extractor.extract_entities(doc)

    def _extract_relations(self, doc: Dict[str, Any]) -> List[RelationRecord]:
        extractor = self._select_extractor(doc)
        return extractor.extract_relations(doc)

    def _add_relation_edge(
        self,
        graph: GraphStore,
        record: RelationRecord,
        entity_key_to_node: Dict[Tuple[str, str], str],
        doc_id: str,
        chunk_id: str,
    ):
        source_value = self.linker.normalize(record.source_type, record.source_value)
        target_value = self.linker.normalize(record.target_type, record.target_value)
        if not source_value or not target_value:
            return

        source_key = (record.source_type, source_value)
        target_key = (record.target_type, target_value)

        source_node_id = entity_key_to_node.get(source_key) or self._entity_node_id(record.source_type, source_value)
        target_node_id = entity_key_to_node.get(target_key) or self._entity_node_id(record.target_type, target_value)

        if source_node_id not in graph.nodes:
            graph.add_node(source_node_id, record.source_type, source_value)
        if target_node_id not in graph.nodes:
            graph.add_node(target_node_id, record.target_type, target_value)

        attrs = {
            "confidence": float(record.confidence),
            "source_chunk_id": chunk_id,
            "doc_id": doc_id,
            "extractor": self._select_extractor_name(record),
        }
        if record.attrs:
            attrs.update(record.attrs)

        graph.add_edge(
            source_node_id,
            target_node_id,
            record.relation,
            weight=float(record.weight),
            bidirectional=record.bidirectional,
            reverse_relation=record.reverse_relation or None,
            attrs=attrs,
        )

    @staticmethod
    def _select_extractor_name(record: RelationRecord) -> str:
        return record.attrs.get("extractor", "relation_extractor") if record.attrs else "relation_extractor"

    @staticmethod
    def _entity_node_id(entity_type: str, entity_value: str) -> str:
        raw = f"{entity_type}:{entity_value}"
        digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]
        return f"{entity_type}:{digest}"
