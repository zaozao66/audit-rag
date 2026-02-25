import hashlib
import logging
import os
import re
from collections import defaultdict, deque
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

import src.indexing.graph.ontology as ontology
from src.indexing.graph.graph_builder import GraphBuilder
from src.indexing.graph.graph_retriever import GraphRetriever
from src.indexing.graph.graph_store import GraphStore
from src.indexing.graph.labels import (
    doc_type_label,
    entity_type_key,
    entity_type_label,
    relation_key,
    relation_label,
)
from src.indexing.metadata.document_metadata_store import DocumentMetadataStore, DocumentRecord
from src.indexing.vector.embedding_providers import EmbeddingProvider
from src.indexing.vector.vector_store import VectorStore
from src.ingestion.splitters.audit_issue_chunker import AuditIssueChunker
from src.ingestion.splitters.audit_report_chunker import AuditReportChunker
from src.ingestion.splitters.document_chunker import DocumentChunker
from src.ingestion.splitters.law_document_chunker import LawDocumentChunker
from src.ingestion.splitters.smart_chunker import SmartChunker
from src.llm.providers.llm_provider import LLMProvider
from src.retrieval.rerank.rerank_provider import RerankProvider
from src.retrieval.router.intent_router import IntentRouter
from src.retrieval.searchers.vector_retriever import VectorRetriever

logger = logging.getLogger(__name__)

PAGE_PATTERN = re.compile(r"\[\[?PAGE:(\d+)\]?\]")
RECTIFICATION_STATUS_LABELS = {
    "completed": "已整改",
    "in_progress": "整改中",
    "pending": "待整改",
}
EVIDENCE_NODE_TYPES = {ontology.ENTITY_CHUNK, ontology.ENTITY_DOCUMENT}


class RAGProcessor:
    """RAG processor orchestrating ingestion, retrieval, graph, and generation."""

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        chunk_size: int = 512,
        overlap: int = 50,
        vector_store_path: str = "./vector_store_text_embedding",
        chunker_type: str = "default",
        rerank_provider: RerankProvider = None,
        llm_provider: LLMProvider = None,
    ):
        self.embedding_provider = embedding_provider
        self.chunker_type = chunker_type
        self.vector_store_path = vector_store_path
        self.rerank_provider = rerank_provider
        self.llm_provider = llm_provider

        self._init_chunker(chunker_type, chunk_size, overlap)
        self.vector_store: Optional[VectorStore] = None
        self.dimension: Optional[int] = None

        self.router = IntentRouter(llm_provider)
        self.retriever: Optional[VectorRetriever] = None

        self.graph_store = GraphStore()
        self.graph_retriever: Optional[GraphRetriever] = None

        metadata_path = vector_store_path.replace("vector_store", "document_metadata") + ".json"
        self.metadata_store = DocumentMetadataStore(storage_path=metadata_path)

        logger.info(
            "RAG处理器初始化完成，重排序功能%s，LLM功能%s",
            "启用" if rerank_provider else "禁用",
            "启用" if llm_provider else "禁用",
        )

    def _init_chunker(self, chunker_type, chunk_size, overlap):
        if chunker_type == "regulation":
            self.chunker = LawDocumentChunker(chunk_size=chunk_size, overlap=overlap)
        elif chunker_type == "audit_report":
            self.chunker = AuditReportChunker(chunk_size=chunk_size, overlap=overlap)
        elif chunker_type == "audit_issue":
            self.chunker = AuditIssueChunker(chunk_size=chunk_size, overlap=overlap)
        elif chunker_type == "smart":
            self.chunker = SmartChunker(chunk_size=chunk_size, overlap=overlap)
        else:
            self.chunker = DocumentChunker(chunk_size=chunk_size, overlap=overlap)
        logger.info("使用【%s】分块器", chunker_type)

    def _graph_store_path(self, base_path: str = None) -> str:
        return f"{base_path or self.vector_store_path}.graph.json"

    def _ensure_vector_store(self):
        if not self.vector_store:
            try:
                self.load_vector_store(self.vector_store_path)
            except Exception as e:
                error_msg = f"向量库不存在，请先处理文档。错误: {str(e)}"
                logger.error(error_msg)
                raise ValueError(error_msg)

        if not self.retriever:
            self.retriever = VectorRetriever(self.vector_store, self.embedding_provider)

    def _ensure_graph_index(self):
        if self.graph_retriever:
            return

        graph_path = self._graph_store_path()
        try:
            if self.graph_store.exists(graph_path):
                self.graph_store.load(graph_path)
            else:
                self.rebuild_graph_index(save=True)
                return

            self.graph_retriever = GraphRetriever(self.graph_store, self.vector_store.documents if self.vector_store else [])
        except Exception as e:
            logger.warning("加载图索引失败，将按需重建: %s", e)
            self.rebuild_graph_index(save=True)

    def _calculate_content_hash(self, content: str) -> str:
        return hashlib.md5(content.encode("utf-8")).hexdigest()

    def _extract_page_nos_and_clean_text(self, text: str) -> Tuple[str, List[int]]:
        page_numbers = [int(m.group(1)) for m in PAGE_PATTERN.finditer(text or "")]
        unique_pages = sorted(set(page_numbers))
        cleaned = PAGE_PATTERN.sub("", text or "")
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        return cleaned, unique_pages

    def _normalize_chunks(self, chunks: List[Dict[str, Any]], doc_id: str) -> List[Dict[str, Any]]:
        normalized = []
        seen_ids = set()

        for idx, chunk in enumerate(chunks):
            text = chunk.get("text", "")
            cleaned_text, page_nos = self._extract_page_nos_and_clean_text(text)
            if not cleaned_text:
                continue

            chunk["text"] = cleaned_text
            chunk["doc_id"] = doc_id

            chunk_id = chunk.get("chunk_id") or f"{doc_id}_chunk_{idx}"
            chunk_id = str(chunk_id)
            if chunk_id in seen_ids:
                chunk_id = f"{chunk_id}_{idx}"
            seen_ids.add(chunk_id)
            chunk["chunk_id"] = chunk_id
            chunk["chunk_index"] = idx

            if page_nos:
                chunk["page_nos"] = page_nos
            elif "page_nos" in chunk and not chunk.get("page_nos"):
                chunk.pop("page_nos", None)

            chunk["char_count"] = len(cleaned_text)
            normalized.append(chunk)

        return normalized

    def _normalize_vector_documents(self) -> bool:
        if not self.vector_store:
            return False

        changed = False
        per_doc_index = defaultdict(int)
        seen_chunk_ids = set()

        for i, doc in enumerate(self.vector_store.documents):
            doc_id = str(doc.get("doc_id") or f"unknown_doc_{i}")
            idx = per_doc_index[doc_id]
            per_doc_index[doc_id] += 1

            cleaned_text, page_nos = self._extract_page_nos_and_clean_text(doc.get("text", ""))
            if cleaned_text != doc.get("text", ""):
                doc["text"] = cleaned_text
                changed = True

            if page_nos and doc.get("page_nos") != page_nos:
                doc["page_nos"] = page_nos
                changed = True

            if not doc.get("doc_id"):
                doc["doc_id"] = doc_id
                changed = True

            old_chunk_id = doc.get("chunk_id")
            chunk_id = str(old_chunk_id) if old_chunk_id else f"{doc_id}_chunk_{idx}"
            if chunk_id in seen_chunk_ids:
                chunk_id = f"{chunk_id}_{idx}"
            seen_chunk_ids.add(chunk_id)

            if chunk_id != old_chunk_id:
                doc["chunk_id"] = chunk_id
                changed = True

            if doc.get("char_count") != len(doc.get("text", "")):
                doc["char_count"] = len(doc.get("text", ""))
                changed = True

        return changed

    def process_documents(self, documents: List[Dict[str, Any]], save_after_processing: bool = True) -> Dict:
        processed_count = 0
        skipped_count = 0
        updated_count = 0

        for doc in documents:
            content = doc["text"]
            content_hash = self._calculate_content_hash(content)
            doc_id = content_hash[:16]

            existing = self.metadata_store.get_document(doc_id)
            if existing and existing.status == "active":
                logger.info("文档已存在，跳过: %s", doc.get("filename", "unknown"))
                skipped_count += 1
                continue

            doc["doc_id"] = doc_id
            chunks = self.chunker.chunk_documents([doc])
            chunks = self._normalize_chunks(chunks, doc_id)

            if not chunks:
                logger.warning("文档未生成有效分块: %s", doc.get("filename", "unknown"))
                continue

            texts = [c["text"] for c in chunks]
            embeddings = self.embedding_provider.get_embeddings(texts)

            if self.vector_store is None:
                if os.path.exists(f"{self.vector_store_path}.index"):
                    self.load_vector_store(self.vector_store_path)
                else:
                    self.dimension = len(embeddings[0]) if embeddings else 1024
                    self.vector_store = VectorStore(dimension=self.dimension)

            self.vector_store.add_embeddings(embeddings, chunks)

            record = DocumentRecord(
                doc_id=doc_id,
                filename=doc.get("filename", "unknown"),
                content_hash=content_hash,
                file_path=doc.get("file_path", ""),
                file_size=len(content.encode("utf-8")),
                doc_type=doc.get("doc_type", "unknown"),
                upload_time=datetime.now().isoformat(),
                chunk_count=len(chunks),
            )

            is_new = self.metadata_store.add_document(record)
            if is_new:
                processed_count += 1
                logger.info("新增文档: %s, chunks: %s", doc.get("filename", "unknown"), len(chunks))
            else:
                updated_count += 1
                logger.info("更新文档: %s", doc.get("filename", "unknown"))

        if self.vector_store:
            self.retriever = VectorRetriever(self.vector_store, self.embedding_provider)
            self._normalize_vector_documents()
            self.rebuild_graph_index(save=save_after_processing)

        if save_after_processing and self.vector_store:
            self.save_vector_store(self.vector_store_path)

        return {
            "processed": processed_count,
            "skipped": skipped_count,
            "updated": updated_count,
            "total_chunks": sum(c.chunk_count for c in self.metadata_store.list_documents()),
        }

    def _search_vector_raw(
        self,
        query: str,
        top_k: int,
        doc_types: List[str] = None,
        titles: List[str] = None,
    ) -> List[Dict[str, Any]]:
        results = self.retriever.search(query, top_k=top_k, doc_types=doc_types, titles=titles)
        formatted = []
        for r in results:
            doc = r.metadata or {}
            if doc.get("status") == "deleted":
                continue
            if not doc.get("text"):
                continue
            formatted.append({
                "document": doc,
                "score": float(r.score),
                "vector_score": float(r.score),
            })
        return formatted

    def _search_graph_raw(
        self,
        query: str,
        top_k: int,
        doc_types: List[str] = None,
        graph_hops: int = 2,
    ) -> List[Dict[str, Any]]:
        self._ensure_graph_index()
        if not self.graph_retriever:
            return []

        results = self.graph_retriever.search(query, top_k=top_k, doc_types=doc_types, hops=graph_hops)
        formatted = []
        for r in results:
            doc = r.metadata or {}
            if doc.get("status") == "deleted":
                continue
            if not doc.get("text"):
                continue
            formatted.append({
                "document": doc,
                "score": float(r.score),
                "graph_score": float(r.score),
            })
        return formatted

    def _normalized_score_map(self, keyed_scores: Dict[str, float]) -> Dict[str, float]:
        if not keyed_scores:
            return {}

        values = list(keyed_scores.values())
        min_v, max_v = min(values), max(values)
        if abs(max_v - min_v) < 1e-9:
            return {k: 1.0 for k in keyed_scores.keys()}
        return {k: (v - min_v) / (max_v - min_v) for k, v in keyed_scores.items()}

    def _result_key(self, doc: Dict[str, Any]) -> str:
        chunk_id = doc.get("chunk_id")
        if chunk_id:
            return f"chunk:{chunk_id}"
        fallback = f"{doc.get('doc_id','')}|{doc.get('filename','')}|{hash(doc.get('text',''))}"
        return f"fallback:{fallback}"

    def _fuse_hybrid_results(
        self,
        vector_results: List[Dict[str, Any]],
        graph_results: List[Dict[str, Any]],
        alpha: float,
    ) -> List[Dict[str, Any]]:
        alpha = max(0.0, min(1.0, alpha))

        merged: Dict[str, Dict[str, Any]] = {}
        vector_scores: Dict[str, float] = {}
        graph_scores: Dict[str, float] = {}

        for item in vector_results:
            key = self._result_key(item["document"])
            merged.setdefault(key, {"document": item["document"]})
            vector_scores[key] = max(vector_scores.get(key, float("-inf")), float(item.get("vector_score", item.get("score", 0.0))))

        for item in graph_results:
            key = self._result_key(item["document"])
            merged.setdefault(key, {"document": item["document"]})
            graph_scores[key] = max(graph_scores.get(key, float("-inf")), float(item.get("graph_score", item.get("score", 0.0))))

        v_norm = self._normalized_score_map(vector_scores)
        g_norm = self._normalized_score_map(graph_scores)

        fused = []
        for key, payload in merged.items():
            v = v_norm.get(key, 0.0)
            g = g_norm.get(key, 0.0)
            score = alpha * v + (1.0 - alpha) * g
            fused.append(
                {
                    "document": payload["document"],
                    "score": score,
                    "vector_score": vector_scores.get(key),
                    "graph_score": graph_scores.get(key),
                }
            )

        fused.sort(key=lambda x: x["score"], reverse=True)
        return fused

    def search(
        self,
        query: str,
        top_k: int = 5,
        use_rerank: bool = False,
        rerank_top_k: int = 10,
        doc_types: List[str] = None,
        titles: List[str] = None,
        use_graph: bool = False,
        retrieval_mode: str = "vector",
        graph_top_k: int = 12,
        graph_hops: int = 2,
        hybrid_alpha: float = 0.65,
    ) -> List[Dict[str, Any]]:
        self._ensure_vector_store()

        mode = (retrieval_mode or "vector").lower()
        if use_graph and mode == "vector":
            mode = "hybrid"
        if mode not in {"vector", "hybrid", "graph"}:
            mode = "vector"

        initial_top_k = max(top_k * 2, rerank_top_k) if use_rerank else top_k

        vector_results: List[Dict[str, Any]] = []
        graph_results: List[Dict[str, Any]] = []

        if mode in {"vector", "hybrid"}:
            vector_results = self._search_vector_raw(
                query,
                top_k=max(initial_top_k, top_k),
                doc_types=doc_types,
                titles=titles,
            )

        if mode in {"graph", "hybrid"}:
            graph_results = self._search_graph_raw(
                query,
                top_k=max(graph_top_k, top_k),
                doc_types=doc_types,
                graph_hops=graph_hops,
            )

        if mode == "vector":
            initial_results = vector_results
        elif mode == "graph":
            initial_results = graph_results
        else:
            initial_results = self._fuse_hybrid_results(vector_results, graph_results, alpha=hybrid_alpha)

        if use_rerank and self.rerank_provider and initial_results:
            docs = [r["document"]["text"] for r in initial_results]
            reranked = self.rerank_provider.rerank(query, docs, top_k=min(len(docs), rerank_top_k))

            final_results = []
            for item in reranked[:top_k]:
                idx = item["index"]
                if idx < len(initial_results):
                    base = initial_results[idx]
                    result = {
                        "score": item["relevance_score"],
                        "document": base["document"],
                        "original_score": base.get("score"),
                    }
                    if base.get("vector_score") is not None:
                        result["vector_score"] = base.get("vector_score")
                    if base.get("graph_score") is not None:
                        result["graph_score"] = base.get("graph_score")
                    final_results.append(result)
            return final_results

        return initial_results[:top_k]

    def search_with_intent(
        self,
        query: str,
        use_rerank: bool = True,
        retrieval_overrides: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        params = self.router.get_routed_params(
            query,
            use_rerank=use_rerank,
            retrieval_overrides=retrieval_overrides,
        )
        search_results = self.search(
            query,
            top_k=params["top_k"],
            use_rerank=params["use_rerank"],
            rerank_top_k=params["rerank_top_k"],
            doc_types=params["doc_types"],
            use_graph=params["use_graph"],
            retrieval_mode=params["retrieval_mode"],
            graph_top_k=params["graph_top_k"],
            graph_hops=params["graph_hops"],
            hybrid_alpha=params["hybrid_alpha"],
        )
        return {
            "query": query,
            "intent": params["intent"],
            "intent_reason": params["reason"],
            "suggested_top_k": params["top_k"],
            "retrieval_mode": params["retrieval_mode"],
            "graph_top_k": params["graph_top_k"],
            "graph_hops": params["graph_hops"],
            "hybrid_alpha": params["hybrid_alpha"],
            "search_results": search_results,
        }

    def search_with_llm_answer(
        self,
        query: str,
        top_k: int = 5,
        use_rerank: bool = True,
        rerank_top_k: int = 10,
        retrieval_overrides: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        if not self.llm_provider:
            raise ValueError("LLM功能未启用，请在初始化时传入llm_provider")

        params = self.router.get_routed_params(
            query,
            default_top_k=top_k,
            use_rerank=use_rerank,
            rerank_top_k=rerank_top_k,
            retrieval_overrides=retrieval_overrides,
        )

        search_results = self.search(
            query,
            top_k=params["top_k"],
            use_rerank=params["use_rerank"],
            rerank_top_k=params["rerank_top_k"],
            doc_types=params["doc_types"],
            use_graph=params["use_graph"],
            retrieval_mode=params["retrieval_mode"],
            graph_top_k=params["graph_top_k"],
            graph_hops=params["graph_hops"],
            hybrid_alpha=params["hybrid_alpha"],
        )

        context_pack = self.build_contexts_and_citations(search_results)
        contexts = context_pack["contexts"]
        citations = context_pack["citations"]

        llm_result = self.llm_provider.generate_answer(query, contexts)

        return {
            "query": query,
            "intent": params["intent"],
            "intent_reason": params["reason"],
            "answer": llm_result["answer"],
            "contexts": contexts,
            "contexts_used": len(contexts),
            "search_results": search_results,
            "citations": citations,
            "llm_usage": llm_result.get("usage", {}),
            "model": llm_result.get("model", ""),
            "retrieval_mode": params["retrieval_mode"],
            "graph_top_k": params["graph_top_k"],
            "graph_hops": params["graph_hops"],
            "hybrid_alpha": params["hybrid_alpha"],
        }

    def _try_load_graph_store_only(self) -> bool:
        if self.graph_store.nodes:
            return True

        graph_path = self._graph_store_path()
        if not os.path.exists(graph_path):
            return False

        try:
            self.graph_store.load(graph_path)
            return bool(self.graph_store.nodes)
        except Exception as e:
            logger.warning("加载图索引用于引用证据失败: %s", e)
            return False

    def _build_incoming_edge_index(self) -> Dict[str, List[Tuple[str, Dict[str, Any]]]]:
        incoming_index: Dict[str, List[Tuple[str, Dict[str, Any]]]] = defaultdict(list)
        for source, neighbors in self.graph_store.edges.items():
            source_id = str(source)
            for edge in neighbors:
                target = str(edge.get("target", ""))
                if not target:
                    continue
                incoming_index[target].append((source_id, edge))
        return incoming_index

    def _decorate_node_by_id(self, node_id: str) -> Dict[str, Any]:
        node = self.graph_store.get_node(node_id)
        if node:
            return self._decorate_node(node)
        return {
            "id": node_id,
            "type": "",
            "name": node_id,
            "type_label": "",
            "name_label": node_id,
            "attrs": {},
        }

    def _build_path_edge_payload(
        self,
        source_id: str,
        target_id: str,
        edge: Dict[str, Any],
        direction: str,
    ) -> Dict[str, Any]:
        source_node = self.graph_store.get_node(source_id) or {}
        source_name = str(source_node.get("name", source_id))
        source_type = str(source_node.get("type", ""))

        target_node = self.graph_store.get_node(target_id) or {}
        target_name = str(target_node.get("name", target_id))
        target_type = str(target_node.get("type", ""))

        relation = str(edge.get("relation", ""))

        return {
            "source": source_id,
            "source_name": source_name,
            "source_name_label": self._label_node_name(source_type, source_name, attrs=source_node.get("attrs", {})),
            "source_type": source_type,
            "source_type_label": entity_type_label(source_type),
            "target": target_id,
            "target_name": target_name,
            "target_name_label": self._label_node_name(target_type, target_name, attrs=target_node.get("attrs", {})),
            "target_type": target_type,
            "target_type_label": entity_type_label(target_type),
            "relation": relation,
            "relation_label": relation_label(relation),
            "weight": float(edge.get("weight", 1.0)),
            "attrs": edge.get("attrs", {}),
            "direction": direction,
            "is_evidence_edge": self._is_evidence_node_type(source_type) or self._is_evidence_node_type(target_type),
        }

    def _build_path_text(self, path_nodes: List[Dict[str, Any]], path_edges: List[Dict[str, Any]]) -> str:
        if not path_nodes:
            return ""

        first = path_nodes[0]
        first_name = str(first.get("name_label") or first.get("name") or first.get("id") or "")
        parts = [first_name]

        for idx, edge in enumerate(path_edges):
            if idx + 1 >= len(path_nodes):
                break
            relation_name = str(edge.get("relation_label") or edge.get("relation") or "关联")
            if edge.get("direction") == "reverse":
                relation_name = f"{relation_name}(逆向)"
            target = path_nodes[idx + 1]
            target_name = str(target.get("name_label") or target.get("name") or target.get("id") or "")
            parts.append(f" -[{relation_name}]- {target_name}")

        return "".join(parts)

    def _find_shortest_path(
        self,
        source_id: str,
        target_id: str,
        max_hops: int,
        incoming_index: Dict[str, List[Tuple[str, Dict[str, Any]]]],
        include_evidence_nodes: bool = True,
    ) -> Optional[Dict[str, Any]]:
        if source_id not in self.graph_store.nodes or target_id not in self.graph_store.nodes:
            return None

        if source_id == target_id:
            node_payload = self._decorate_node_by_id(source_id)
            return {
                "node_ids": [source_id],
                "nodes": [node_payload],
                "edges": [],
                "path_text": str(node_payload.get("name_label") or node_payload.get("name") or source_id),
                "hops": 0,
            }

        q = deque([source_id])
        depth: Dict[str, int] = {source_id: 0}
        parent: Dict[str, Tuple[str, Dict[str, Any], str]] = {}

        while q:
            current = q.popleft()
            current_depth = depth.get(current, 0)
            if current_depth >= max_hops:
                continue

            for edge in self.graph_store.neighbors(current):
                nxt = str(edge.get("target", ""))
                if not nxt or nxt not in self.graph_store.nodes:
                    continue
                if nxt in depth:
                    continue
                if not include_evidence_nodes:
                    nxt_node = self.graph_store.get_node(nxt) or {}
                    nxt_type = str(nxt_node.get("type", ""))
                    if self._is_evidence_node_type(nxt_type):
                        continue

                depth[nxt] = current_depth + 1
                parent[nxt] = (current, edge, "forward")
                if nxt == target_id:
                    q.clear()
                    break
                q.append(nxt)

            if target_id in parent:
                break

            for prev_id, edge in incoming_index.get(current, []):
                if not prev_id or prev_id not in self.graph_store.nodes:
                    continue
                if prev_id in depth:
                    continue
                if not include_evidence_nodes:
                    prev_node = self.graph_store.get_node(prev_id) or {}
                    prev_type = str(prev_node.get("type", ""))
                    if self._is_evidence_node_type(prev_type):
                        continue

                depth[prev_id] = current_depth + 1
                parent[prev_id] = (current, edge, "reverse")
                if prev_id == target_id:
                    q.clear()
                    break
                q.append(prev_id)

            if target_id in parent:
                break

        if target_id not in parent:
            return None

        node_ids = [target_id]
        step_records: List[Tuple[str, str, Dict[str, Any], str]] = []
        cursor = target_id

        while cursor != source_id:
            parent_node, edge, direction = parent[cursor]
            step_records.append((parent_node, cursor, edge, direction))
            node_ids.append(parent_node)
            cursor = parent_node

        node_ids.reverse()
        step_records.reverse()

        path_nodes = [self._decorate_node_by_id(node_id) for node_id in node_ids]
        path_edges = [
            self._build_path_edge_payload(step_source, step_target, edge, direction)
            for step_source, step_target, edge, direction in step_records
        ]
        path_text = self._build_path_text(path_nodes, path_edges)

        return {
            "node_ids": node_ids,
            "nodes": path_nodes,
            "edges": path_edges,
            "path_text": path_text,
            "hops": len(path_edges),
        }

    def _resolve_graph_node(
        self,
        node_id: str = "",
        query: str = "",
        max_candidates: int = 5,
        include_evidence_nodes: bool = True,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        normalized_node_id = str(node_id or "").strip()
        if normalized_node_id and normalized_node_id in self.graph_store.nodes:
            selected = self.graph_store.nodes[normalized_node_id]
            selected_type = str(selected.get("type", ""))
            if not include_evidence_nodes and self._is_evidence_node_type(selected_type):
                return "", []
            return normalized_node_id, [{**self._decorate_node(selected), "score": 1.0}]

        query_text = str(query or "").strip()
        if not query_text:
            return "", []

        candidates: List[Dict[str, Any]] = []
        matches = self.graph_store.find_nodes_by_query(query_text, max_nodes=max_candidates)
        for match in matches:
            match_id = str(match.get("node_id", ""))
            if not match_id:
                continue
            node = self.graph_store.get_node(match_id)
            if not node:
                continue
            node_type = str(node.get("type", ""))
            if not include_evidence_nodes and self._is_evidence_node_type(node_type):
                continue
            candidates.append({**self._decorate_node(node), "score": float(match.get("score", 0.0))})

        selected_id = str(candidates[0].get("id", "")) if candidates else ""
        return selected_id, candidates

    def _resolve_query_seed_matches(self, query: str, max_nodes: int = 8) -> List[Dict[str, Any]]:
        query_text = str(query or "").strip()
        if not query_text:
            return []

        matched = []
        for item in self.graph_store.find_nodes_by_query(query_text, max_nodes=max_nodes):
            node_id = str(item.get("node_id", ""))
            if not node_id:
                continue
            node = self.graph_store.get_node(node_id)
            if not node:
                continue
            matched.append(
                {
                    "node_id": node_id,
                    "score": float(item.get("score", 0.0)),
                    "node": node,
                }
            )
        return matched

    def _build_graph_evidence_for_chunk(
        self,
        chunk_id: str,
        seed_matches: List[Dict[str, Any]],
        incoming_index: Dict[str, List[Tuple[str, Dict[str, Any]]]],
        max_hops: int = 4,
    ) -> Optional[Dict[str, Any]]:
        if not chunk_id or not seed_matches:
            return None

        chunk_node_id = f"{ontology.ENTITY_CHUNK}:{chunk_id}"
        if chunk_node_id not in self.graph_store.nodes:
            return None

        best_path: Optional[Dict[str, Any]] = None
        best_seed: Optional[Dict[str, Any]] = None

        for seed in seed_matches:
            seed_id = str(seed.get("node_id", ""))
            if not seed_id:
                continue
            path = self._find_shortest_path(seed_id, chunk_node_id, max_hops=max_hops, incoming_index=incoming_index)
            if not path:
                continue

            if best_path is None:
                best_path = path
                best_seed = seed
                continue

            prev_hops = int(best_path.get("hops", 10_000))
            curr_hops = int(path.get("hops", 10_000))
            prev_seed_score = float(best_seed.get("score", 0.0)) if best_seed else 0.0
            curr_seed_score = float(seed.get("score", 0.0))

            if curr_hops < prev_hops or (curr_hops == prev_hops and curr_seed_score > prev_seed_score):
                best_path = path
                best_seed = seed

        if not best_path or not best_seed:
            return None

        seed_node = best_seed.get("node") or {}
        seed_type = str(seed_node.get("type", ""))
        seed_name = str(seed_node.get("name", ""))

        return {
            "seed_node_id": str(best_seed.get("node_id", "")),
            "seed_name": seed_name,
            "seed_name_label": self._label_node_name(seed_type, seed_name),
            "seed_type": seed_type,
            "seed_type_label": entity_type_label(seed_type),
            "seed_score": float(best_seed.get("score", 0.0)),
            "hops": int(best_path.get("hops", 0)),
            "path_text": str(best_path.get("path_text", "")),
            "path_nodes": best_path.get("nodes", []),
            "path_edges": best_path.get("edges", []),
        }

    def build_contexts_and_citations(
        self,
        search_results: List[Dict[str, Any]],
        query: str = "",
    ) -> Dict[str, List[Dict[str, Any]]]:
        contexts: List[Dict[str, Any]] = []
        citations: List[Dict[str, Any]] = []
        evidence_cache: Dict[str, Optional[Dict[str, Any]]] = {}

        seed_matches: List[Dict[str, Any]] = []
        incoming_index: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
        if query and self._try_load_graph_store_only():
            seed_matches = self._resolve_query_seed_matches(query, max_nodes=10)
            if seed_matches:
                incoming_index = self._build_incoming_edge_index()

        for idx, res in enumerate(search_results, 1):
            doc = res.get("document", {})
            source_id = f"S{idx}"
            raw_text = doc.get("text", "") or ""
            text_preview = raw_text[:220] + ("..." if len(raw_text) > 220 else "")
            chunk_id = str(doc.get("chunk_id", "") or "")

            graph_evidence = None
            if seed_matches and incoming_index and chunk_id:
                if chunk_id not in evidence_cache:
                    evidence_cache[chunk_id] = self._build_graph_evidence_for_chunk(
                        chunk_id=chunk_id,
                        seed_matches=seed_matches,
                        incoming_index=incoming_index,
                        max_hops=4,
                    )
                graph_evidence = evidence_cache.get(chunk_id)

            contexts.append(
                {
                    "source_id": source_id,
                    "text": raw_text,
                    "title": doc.get("title", ""),
                    "filename": doc.get("filename", ""),
                    "doc_type": doc.get("doc_type", ""),
                    "score": res.get("score", 0.0),
                    "doc_id": doc.get("doc_id", ""),
                    "chunk_id": doc.get("chunk_id", ""),
                    "page_nos": doc.get("page_nos", []),
                    "header": doc.get("header", ""),
                    "section_path": doc.get("section_path", []),
                    "vector_score": res.get("vector_score"),
                    "graph_score": res.get("graph_score"),
                }
            )

            citation_item = {
                "source_id": source_id,
                "doc_id": doc.get("doc_id", ""),
                "chunk_id": chunk_id,
                "filename": doc.get("filename", ""),
                "title": doc.get("title", ""),
                "doc_type": doc.get("doc_type", ""),
                "score": res.get("score", 0.0),
                "original_score": res.get("original_score"),
                "vector_score": res.get("vector_score"),
                "graph_score": res.get("graph_score"),
                "text_preview": text_preview,
                "page_nos": doc.get("page_nos", []),
                "header": doc.get("header", ""),
                "section_path": doc.get("section_path", []),
            }
            if graph_evidence:
                citation_item["graph_evidence"] = graph_evidence
            citations.append(citation_item)

        return {"contexts": contexts, "citations": citations}

    def save_vector_store(self, filepath: str = None):
        if not self.vector_store:
            return
        self.vector_store.save(filepath or self.vector_store_path)

    def load_vector_store(self, filepath: str = None):
        path = filepath or self.vector_store_path
        self.vector_store = VectorStore(dimension=self.dimension or 1024)
        self.vector_store.load(path)
        self.dimension = self.vector_store.index.d

        changed = self._normalize_vector_documents()
        if changed:
            self.vector_store.save(path)

        self.retriever = VectorRetriever(self.vector_store, self.embedding_provider)

        if self.graph_retriever:
            self.graph_retriever.refresh_documents(self.vector_store.documents)

    def rebuild_graph_index(self, save: bool = True) -> Dict[str, Any]:
        if not self.vector_store:
            return {"nodes": 0, "edges": 0, "by_type": {}}

        builder = GraphBuilder()
        self.graph_store = builder.build(self.vector_store.documents)
        self.graph_retriever = GraphRetriever(self.graph_store, self.vector_store.documents)

        stats = self.graph_store.get_stats()

        if save:
            self.graph_store.save(self._graph_store_path())

        return stats

    def get_graph_stats(self) -> Dict[str, Any]:
        graph_path = self._graph_store_path()
        if not self.graph_store.nodes and os.path.exists(graph_path):
            try:
                self.graph_store.load(graph_path)
                if self.vector_store and not self.graph_retriever:
                    self.graph_retriever = GraphRetriever(self.graph_store, self.vector_store.documents)
            except Exception as e:
                logger.warning("加载图索引统计失败，将返回当前内存统计: %s", e)

        in_memory_stats = self.graph_store.get_stats()
        by_type = in_memory_stats.get("by_type", {})
        in_memory_stats["by_type_labels"] = {k: entity_type_label(k) for k in by_type.keys()}

        return {
            "graph_file_exists": os.path.exists(graph_path),
            "graph_path": graph_path,
            "in_memory": in_memory_stats,
        }

    def _ensure_graph_store_loaded(self):
        if self.graph_store.nodes:
            return

        graph_path = self._graph_store_path()
        if os.path.exists(graph_path):
            self.graph_store.load(graph_path)
            return

        self._ensure_vector_store()
        self.rebuild_graph_index(save=True)

    @staticmethod
    def _is_evidence_node_type(node_type: str) -> bool:
        return str(node_type or "") in EVIDENCE_NODE_TYPES

    @staticmethod
    def _format_pages(page_nos: List[Any], max_len: int = 3) -> str:
        values = []
        for p in page_nos or []:
            try:
                values.append(int(p))
            except (TypeError, ValueError):
                continue
        values = sorted(set(values))
        if not values:
            return ""
        if len(values) <= max_len:
            return "p." + ",".join(str(v) for v in values)
        return "p." + ",".join(str(v) for v in values[:max_len]) + "..."

    @staticmethod
    def _chunk_name_label(attrs: Dict[str, Any], fallback: str) -> str:
        filename = str(attrs.get("filename", "") or attrs.get("title", "") or "").strip()
        pages = RAGProcessor._format_pages(attrs.get("page_nos", []), max_len=3)
        header = str(attrs.get("header", "") or "").strip()
        semantic_boundary = str(attrs.get("semantic_boundary", "") or "").strip()
        text_preview = str(attrs.get("text_preview", "") or "").strip()

        parts = []
        if filename:
            parts.append(filename)
        if pages:
            parts.append(pages)
        if header:
            parts.append(header[:30])
        elif semantic_boundary:
            parts.append(semantic_boundary[:30])
        elif text_preview:
            parts.append(text_preview[:30])

        if parts:
            return " | ".join(parts)
        return fallback

    def _label_node_name(self, node_type: str, node_name: str, attrs: Optional[Dict[str, Any]] = None) -> str:
        attrs = attrs or {}
        if node_type == "doc_type":
            return doc_type_label(node_name)
        if node_type == "rectification_status":
            return RECTIFICATION_STATUS_LABELS.get(node_name, node_name)
        if node_type == ontology.ENTITY_CHUNK:
            return self._chunk_name_label(attrs, node_name)
        return node_name

    def _decorate_node(self, node: Dict[str, Any]) -> Dict[str, Any]:
        node_type_key = str(node.get("type", ""))
        node_name = str(node.get("name", ""))
        attrs = node.get("attrs", {}) or {}
        payload = {
            **node,
            "type_label": entity_type_label(node_type_key),
            "name_label": self._label_node_name(node_type_key, node_name, attrs=attrs),
            "is_evidence": self._is_evidence_node_type(node_type_key),
        }
        return payload

    def _build_edge_payload(self, source: str, edge: Dict[str, Any]) -> Dict[str, Any]:
        source_node = self.graph_store.get_node(source) or {}
        source_name = str(source_node.get("name", source))
        source_type = str(source_node.get("type", ""))

        target = str(edge.get("target", ""))
        target_node = self.graph_store.get_node(target) or {}
        target_name = str(target_node.get("name", target))
        target_type = str(target_node.get("type", ""))

        relation = str(edge.get("relation", ""))

        return {
            "source": source,
            "source_name": source_name,
            "source_name_label": self._label_node_name(source_type, source_name, attrs=source_node.get("attrs", {})),
            "source_type": source_type,
            "source_type_label": entity_type_label(source_type),
            "target": target,
            "target_name": target_name,
            "target_name_label": self._label_node_name(target_type, target_name, attrs=target_node.get("attrs", {})),
            "target_type": target_type,
            "target_type_label": entity_type_label(target_type),
            "relation": relation,
            "relation_label": relation_label(relation),
            "weight": float(edge.get("weight", 1.0)),
            "attrs": edge.get("attrs", {}),
            "is_evidence_edge": self._is_evidence_node_type(source_type) or self._is_evidence_node_type(target_type),
        }

    def get_graph_overview(self, top_n: int = 8) -> Dict[str, Any]:
        self._ensure_graph_store_loaded()
        safe_top_n = max(3, min(50, int(top_n)))

        stats = self.graph_store.get_stats()
        node_type_counts = stats.get("by_type", {})

        node_type_distribution = [
            {
                "type": t,
                "label": entity_type_label(t),
                "count": int(c),
            }
            for t, c in sorted(node_type_counts.items(), key=lambda item: item[1], reverse=True)
        ]

        relation_counts: Dict[str, int] = defaultdict(int)
        for neighbors in self.graph_store.edges.values():
            for edge in neighbors:
                rel = str(edge.get("relation", ""))
                if rel:
                    relation_counts[rel] += 1

        relation_distribution = [
            {
                "relation": rel,
                "label": relation_label(rel),
                "count": int(count),
            }
            for rel, count in sorted(relation_counts.items(), key=lambda item: item[1], reverse=True)[:safe_top_n]
        ]

        status_counts: Dict[str, int] = defaultdict(int)
        for node in self.graph_store.nodes.values():
            if str(node.get("type", "")) != "rectification_status":
                continue
            raw_name = str(node.get("name", ""))
            status_label = self._label_node_name("rectification_status", raw_name)
            status_counts[status_label] += 1

        rectification_status_distribution = [
            {
                "status": status,
                "label": status,
                "count": int(count),
            }
            for status, count in sorted(status_counts.items(), key=lambda item: item[1], reverse=True)
        ]

        department_issues: Dict[str, Set[str]] = defaultdict(set)
        for node_id, node in self.graph_store.nodes.items():
            if str(node.get("type", "")) != "issue":
                continue
            for edge in self.graph_store.neighbors(node_id):
                if str(edge.get("relation", "")) != "belongs_to_department":
                    continue
                target_id = str(edge.get("target", ""))
                target_node = self.graph_store.get_node(target_id) or {}
                if str(target_node.get("type", "")) != "department":
                    continue
                dept_name = str(target_node.get("name", ""))
                if dept_name:
                    department_issues[dept_name].add(node_id)

        department_issue_top = [
            {
                "department": dept,
                "issue_count": len(issue_ids),
            }
            for dept, issue_ids in sorted(
                department_issues.items(), key=lambda item: len(item[1]), reverse=True
            )[:safe_top_n]
        ]

        return {
            "nodes": int(stats.get("nodes", 0)),
            "edges": int(stats.get("edges", 0)),
            "node_type_distribution": node_type_distribution,
            "relation_distribution": relation_distribution,
            "rectification_status_distribution": rectification_status_distribution,
            "department_issue_top": department_issue_top,
        }

    def get_graph_node_detail(self, node_id: str, max_neighbors: int = 120) -> Dict[str, Any]:
        self._ensure_graph_store_loaded()
        safe_limit = max(20, min(300, int(max_neighbors)))

        node = self.graph_store.get_node(node_id)
        if not node:
            return {}

        outgoing_edges = []
        for edge in self.graph_store.neighbors(node_id):
            outgoing_edges.append(self._build_edge_payload(node_id, edge))
            if len(outgoing_edges) >= safe_limit:
                break

        incoming_edges = []
        for source, neighbors in self.graph_store.edges.items():
            for edge in neighbors:
                if str(edge.get("target", "")) != node_id:
                    continue
                incoming_edges.append(self._build_edge_payload(source, edge))
                if len(incoming_edges) >= safe_limit:
                    break
            if len(incoming_edges) >= safe_limit:
                break

        outgoing_edges.sort(key=lambda e: (str(e.get("relation", "")), str(e.get("target_name", ""))))
        incoming_edges.sort(key=lambda e: (str(e.get("relation", "")), str(e.get("source_name", ""))))

        neighbor_ids = {str(e.get("target", "")) for e in outgoing_edges}
        neighbor_ids.update({str(e.get("source", "")) for e in incoming_edges})
        neighbor_ids.discard(node_id)

        neighbors = []
        for neighbor_id in neighbor_ids:
            neighbor_node = self.graph_store.get_node(neighbor_id)
            if neighbor_node:
                neighbors.append(self._decorate_node(neighbor_node))
        neighbors.sort(key=lambda n: (str(n.get("type", "")), str(n.get("name", ""))))

        source_map: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for edge in outgoing_edges + incoming_edges:
            attrs = edge.get("attrs", {}) or {}
            doc_id = str(attrs.get("doc_id", "") or "")
            chunk_id = str(attrs.get("source_chunk_id", "") or "")
            extractor = str(attrs.get("extractor", "") or "")
            confidence = float(attrs.get("confidence", 0.0) or 0.0)

            if not doc_id and not chunk_id:
                continue

            source_key = (doc_id, chunk_id, extractor)
            prev = source_map.get(source_key)
            if prev is None or confidence > float(prev.get("confidence", 0.0)):
                source_map[source_key] = {
                    "doc_id": doc_id,
                    "chunk_id": chunk_id,
                    "extractor": extractor,
                    "confidence": confidence,
                }

        sources = sorted(
            source_map.values(),
            key=lambda item: float(item.get("confidence", 0.0)),
            reverse=True,
        )

        source_chunks: List[Dict[str, Any]] = []
        if sources:
            if not self.vector_store:
                try:
                    self.load_vector_store(self.vector_store_path)
                except Exception:
                    pass

            if self.vector_store:
                docs_by_chunk: Dict[str, Dict[str, Any]] = {}
                for d in self.vector_store.documents:
                    chunk_id = str(d.get("chunk_id", "") or "")
                    if chunk_id and chunk_id not in docs_by_chunk:
                        docs_by_chunk[chunk_id] = d

                for src in sources:
                    chunk_id = str(src.get("chunk_id", "") or "")
                    if not chunk_id:
                        continue
                    doc = docs_by_chunk.get(chunk_id)
                    if not doc:
                        continue
                    text = str(doc.get("text", "") or "")
                    source_chunks.append(
                        {
                            "chunk_id": chunk_id,
                            "doc_id": doc.get("doc_id", ""),
                            "filename": doc.get("filename", ""),
                            "title": doc.get("title", ""),
                            "doc_type": doc.get("doc_type", ""),
                            "doc_type_label": doc_type_label(str(doc.get("doc_type", ""))),
                            "page_nos": doc.get("page_nos", []),
                            "header": doc.get("header", ""),
                            "text_preview": text[:220] + ("..." if len(text) > 220 else ""),
                        }
                    )

        return {
            "node": self._decorate_node(node),
            "outgoing_edges": outgoing_edges,
            "incoming_edges": incoming_edges,
            "neighbors": neighbors,
            "sources": sources,
            "source_chunks": source_chunks,
        }

    def list_graph_nodes(
        self,
        page: int = 1,
        page_size: int = 20,
        node_type: str = None,
        keyword: str = None,
        include_evidence_nodes: bool = False,
    ) -> Dict[str, Any]:
        self._ensure_graph_store_loaded()

        type_filter = entity_type_key((node_type or "").strip())
        keyword_filter = (keyword or "").strip().lower()

        type_options = sorted(
            {
                str(node.get("type", "")).strip()
                for node in self.graph_store.nodes.values()
                if str(node.get("type", "")).strip()
                and (include_evidence_nodes or not self._is_evidence_node_type(str(node.get("type", ""))))
            }
        )

        nodes = []
        for node in self.graph_store.nodes.values():
            node_type_value = str(node.get("type", ""))
            if not include_evidence_nodes and self._is_evidence_node_type(node_type_value):
                continue
            if type_filter and node.get("type") != type_filter:
                continue
            if keyword_filter:
                name = str(node.get("name", "")).lower()
                attrs_text = str(node.get("attrs", "")).lower()
                if keyword_filter not in name and keyword_filter not in attrs_text:
                    continue
            nodes.append(self._decorate_node(node))

        nodes.sort(key=lambda n: (str(n.get("type", "")), str(n.get("name", ""))))
        total = len(nodes)
        start = (page - 1) * page_size
        end = start + page_size

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "nodes": nodes[start:end],
            "type_options": [{"value": key, "label": entity_type_label(key)} for key in type_options],
        }

    def list_graph_edges(
        self,
        page: int = 1,
        page_size: int = 20,
        relation: str = None,
        keyword: str = None,
        include_evidence_nodes: bool = False,
    ) -> Dict[str, Any]:
        self._ensure_graph_store_loaded()

        relation_filter = relation_key((relation or "").strip())
        keyword_filter = (keyword or "").strip().lower()
        relation_options_set = set()
        edge_agg: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

        for source, neighbors in self.graph_store.edges.items():
            for edge in neighbors:
                edge_payload = self._build_edge_payload(source, edge)
                if not include_evidence_nodes:
                    if self._is_evidence_node_type(str(edge_payload.get("source_type", ""))):
                        continue
                    if self._is_evidence_node_type(str(edge_payload.get("target_type", ""))):
                        continue

                rel = edge.get("relation", "")
                relation_value = str(edge_payload.get("relation", "")).strip()
                if relation_value:
                    relation_options_set.add(relation_value)

                if relation_filter and rel != relation_filter:
                    continue

                if keyword_filter:
                    edge_text = (
                        f"{edge_payload.get('source_name', '')} "
                        f"{edge_payload.get('source_type', '')} "
                        f"{edge_payload.get('relation', '')} "
                        f"{edge_payload.get('target_name', '')} "
                        f"{edge_payload.get('target_type', '')}"
                    ).lower()
                    if keyword_filter not in edge_text:
                        continue

                signature = (
                    str(edge_payload.get("source", "")),
                    str(edge_payload.get("target", "")),
                    relation_value,
                )
                attrs = dict(edge_payload.get("attrs", {}) or {})
                confidence = float(attrs.get("confidence", 0.0) or 0.0)

                if signature not in edge_agg:
                    new_payload = {**edge_payload}
                    new_attrs = {**attrs, "evidence_count": 1}
                    if confidence > 0:
                        new_attrs["confidence_max"] = confidence
                    new_payload["attrs"] = new_attrs
                    edge_agg[signature] = new_payload
                else:
                    existing = edge_agg[signature]
                    existing_attrs = dict(existing.get("attrs", {}) or {})
                    existing_attrs["evidence_count"] = int(existing_attrs.get("evidence_count", 1)) + 1
                    prev_conf = float(existing_attrs.get("confidence_max", 0.0) or 0.0)
                    if confidence > prev_conf:
                        existing_attrs["confidence_max"] = confidence
                    existing["attrs"] = existing_attrs
                    if float(edge_payload.get("weight", 0.0) or 0.0) > float(existing.get("weight", 0.0) or 0.0):
                        existing["weight"] = edge_payload.get("weight", existing.get("weight", 1.0))

        relation_options = sorted(relation_options_set)
        edges = list(edge_agg.values())

        edges.sort(key=lambda e: (str(e.get("relation", "")), str(e.get("source_name", "")), str(e.get("target_name", ""))))
        total = len(edges)
        start = (page - 1) * page_size
        end = start + page_size

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "edges": edges[start:end],
            "relation_options": [{"value": key, "label": relation_label(key)} for key in relation_options],
        }

    def get_graph_subgraph(
        self,
        query: str = None,
        node_ids: List[str] = None,
        hops: int = 2,
        max_nodes: int = 120,
        include_evidence_nodes: bool = False,
    ) -> Dict[str, Any]:
        self._ensure_graph_store_loaded()

        safe_hops = max(1, min(4, int(hops)))
        safe_max_nodes = max(20, min(300, int(max_nodes)))

        seed_nodes = set()
        for node_id in node_ids or []:
            if node_id in self.graph_store.nodes:
                node = self.graph_store.get_node(node_id) or {}
                if not include_evidence_nodes and self._is_evidence_node_type(str(node.get("type", ""))):
                    continue
                seed_nodes.add(node_id)

        if query:
            matches = self.graph_store.find_nodes_by_query(query, max_nodes=12)
            for m in matches:
                candidate_id = str(m.get("node_id", ""))
                if not candidate_id:
                    continue
                candidate_node = self.graph_store.get_node(candidate_id) or {}
                if not include_evidence_nodes and self._is_evidence_node_type(str(candidate_node.get("type", ""))):
                    continue
                seed_nodes.add(candidate_id)

        if not seed_nodes:
            return {
                "seed_nodes": [],
                "nodes": [],
                "edges": [],
                "hops": safe_hops,
                "max_nodes": safe_max_nodes,
            }

        visited = set(seed_nodes)
        q = deque([(node_id, 0) for node_id in seed_nodes])

        while q and len(visited) < safe_max_nodes:
            node_id, depth = q.popleft()
            if depth >= safe_hops:
                continue

            for edge in self.graph_store.neighbors(node_id):
                target = edge.get("target")
                if not target or target not in self.graph_store.nodes:
                    continue
                target_node = self.graph_store.get_node(target) or {}
                if not include_evidence_nodes and self._is_evidence_node_type(str(target_node.get("type", ""))):
                    continue
                if target in visited:
                    continue
                visited.add(target)
                q.append((target, depth + 1))
                if len(visited) >= safe_max_nodes:
                    break

        nodes = []
        for node_id in visited:
            if node_id not in self.graph_store.nodes:
                continue
            node = self.graph_store.nodes[node_id]
            nodes.append(self._decorate_node(node))
        nodes.sort(key=lambda n: (str(n.get("type", "")), str(n.get("name", ""))))

        edge_agg: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for source in visited:
            for edge in self.graph_store.neighbors(source):
                target = edge.get("target")
                relation = edge.get("relation", "")
                if target not in visited:
                    continue
                source_node = self.graph_store.get_node(source) or {}
                target_node = self.graph_store.get_node(target) or {}
                if not include_evidence_nodes:
                    if self._is_evidence_node_type(str(source_node.get("type", ""))):
                        continue
                    if self._is_evidence_node_type(str(target_node.get("type", ""))):
                        continue
                signature = (source, target, relation)
                payload = self._build_edge_payload(source, edge)
                attrs = dict(payload.get("attrs", {}) or {})
                confidence = float(attrs.get("confidence", 0.0) or 0.0)

                if signature not in edge_agg:
                    new_attrs = {**attrs, "evidence_count": 1}
                    if confidence > 0:
                        new_attrs["confidence_max"] = confidence
                    edge_agg[signature] = {**payload, "attrs": new_attrs}
                else:
                    existing = edge_agg[signature]
                    existing_attrs = dict(existing.get("attrs", {}) or {})
                    existing_attrs["evidence_count"] = int(existing_attrs.get("evidence_count", 1)) + 1
                    prev_conf = float(existing_attrs.get("confidence_max", 0.0) or 0.0)
                    if confidence > prev_conf:
                        existing_attrs["confidence_max"] = confidence
                    existing["attrs"] = existing_attrs
                    if float(payload.get("weight", 0.0) or 0.0) > float(existing.get("weight", 0.0) or 0.0):
                        existing["weight"] = payload.get("weight", existing.get("weight", 1.0))

        edges = list(edge_agg.values())

        edges.sort(key=lambda e: (str(e.get("relation", "")), str(e.get("source_name", "")), str(e.get("target_name", ""))))

        return {
            "seed_nodes": list(seed_nodes),
            "nodes": nodes,
            "edges": edges,
            "hops": safe_hops,
            "max_nodes": safe_max_nodes,
        }

    def get_graph_path(
        self,
        source_node_id: str = "",
        target_node_id: str = "",
        source_query: str = "",
        target_query: str = "",
        max_hops: int = 4,
        max_candidates: int = 5,
        include_evidence_nodes: bool = False,
    ) -> Dict[str, Any]:
        self._ensure_graph_store_loaded()

        safe_hops = max(1, min(8, int(max_hops)))
        safe_candidates = max(1, min(10, int(max_candidates)))

        resolved_source_id, source_candidates = self._resolve_graph_node(
            node_id=source_node_id,
            query=source_query,
            max_candidates=safe_candidates,
            include_evidence_nodes=include_evidence_nodes,
        )
        resolved_target_id, target_candidates = self._resolve_graph_node(
            node_id=target_node_id,
            query=target_query,
            max_candidates=safe_candidates,
            include_evidence_nodes=include_evidence_nodes,
        )

        result: Dict[str, Any] = {
            "source_node": self._decorate_node_by_id(resolved_source_id) if resolved_source_id else None,
            "target_node": self._decorate_node_by_id(resolved_target_id) if resolved_target_id else None,
            "source_candidates": source_candidates,
            "target_candidates": target_candidates,
            "path_found": False,
            "path_nodes": [],
            "path_edges": [],
            "path_text": "",
            "hops": 0,
            "max_hops": safe_hops,
            "include_evidence_nodes": bool(include_evidence_nodes),
        }

        if not resolved_source_id or not resolved_target_id:
            return result

        incoming_index = self._build_incoming_edge_index()
        path = self._find_shortest_path(
            source_id=resolved_source_id,
            target_id=resolved_target_id,
            max_hops=safe_hops,
            incoming_index=incoming_index,
            include_evidence_nodes=include_evidence_nodes,
        )
        if not path:
            return result

        result.update(
            {
                "path_found": True,
                "path_nodes": path.get("nodes", []),
                "path_edges": path.get("edges", []),
                "path_text": path.get("path_text", ""),
                "hops": int(path.get("hops", 0)),
            }
        )
        return result

    def clear_vector_store(self):
        if self.vector_store:
            self.vector_store = VectorStore(dimension=self.dimension or 1024)
            self.retriever = VectorRetriever(self.vector_store, self.embedding_provider)

        self.graph_store.clear()
        self.graph_retriever = None
        graph_path = self._graph_store_path()
        if os.path.exists(graph_path):
            os.remove(graph_path)

    def process_documents_from_files(
        self,
        file_paths: List[str],
        save_after_processing: bool = True,
        doc_type: str = "internal_regulation",
        title: str = None,
        original_filenames: List[str] = None,
    ) -> Dict:
        from src.ingestion.parsers.document_processor import process_uploaded_documents

        processed_documents = process_uploaded_documents(
            file_paths,
            doc_type=doc_type,
            title=title,
            original_filenames=original_filenames,
        )
        if not processed_documents:
            return {"processed": 0, "skipped": 0, "updated": 0, "total_chunks": 0}
        return self.process_documents(processed_documents, save_after_processing=save_after_processing)

    def list_documents(self, doc_type: str = None, keyword: str = None, include_deleted: bool = False) -> List[Dict]:
        status = None if include_deleted else "active"
        records = self.metadata_store.list_documents(doc_type=doc_type, status=status, keyword=keyword)
        return [r.to_dict() for r in records]

    def get_document_detail(self, doc_id: str) -> Optional[Dict]:
        record = self.metadata_store.get_document(doc_id)
        if not record:
            return None

        detail = record.to_dict()

        if not self.vector_store:
            try:
                self.load_vector_store(self.vector_store_path)
            except Exception:
                # 文档详情在向量库不可用时仍可返回基础元数据
                return detail

        if self.vector_store:
            chunks = self.vector_store.get_document_chunks(doc_id)
            detail["chunks"] = chunks

        return detail

    def get_document_chunks(self, doc_id: str, include_text: bool = True) -> Dict:
        record = self.metadata_store.get_document(doc_id)
        if not record:
            return {"error": "文档不存在"}

        if not self.vector_store:
            try:
                self.load_vector_store(self.vector_store_path)
            except Exception as e:
                return {"error": f"向量库未加载: {str(e)}"}

        chunks = self.vector_store.get_document_chunks(doc_id)

        total_chars = sum(c["char_count"] for c in chunks)
        avg_chunk_size = total_chars // len(chunks) if chunks else 0

        if not include_text:
            chunks = [{k: v for k, v in c.items() if k != "text"} for c in chunks]

        return {
            "doc_id": doc_id,
            "filename": record.filename,
            "doc_type": record.doc_type,
            "upload_time": record.upload_time,
            "chunk_count": len(chunks),
            "total_chars": total_chars,
            "avg_chunk_size": avg_chunk_size,
            "chunks": chunks,
        }

    def delete_document(self, doc_id: str) -> Dict:
        if not self.metadata_store.delete_document(doc_id):
            return {"success": False, "error": "文档不存在"}

        removed_chunks = 0
        if self.vector_store:
            removed_chunks = self.vector_store.remove_document_chunks(doc_id)

        if self.vector_store:
            self.save_vector_store(self.vector_store_path)
            self.rebuild_graph_index(save=True)

        return {
            "success": True,
            "doc_id": doc_id,
            "removed_chunks": removed_chunks,
        }

    def get_document_stats(self) -> Dict:
        return self.metadata_store.get_stats()

    def clear_all_documents(self) -> Dict:
        doc_stats = self.metadata_store.clear_all(delete_storage_file=True)

        if self.vector_store:
            self.clear_vector_store()
            if self.retriever:
                self.retriever = VectorRetriever(self.vector_store, self.embedding_provider)

        removed_vector_files = 0
        for suffix in (".index", ".docs", ".graph.json"):
            path = f"{self.vector_store_path}{suffix}"
            if os.path.exists(path):
                os.remove(path)
                removed_vector_files += 1

        return {
            "success": True,
            "removed_documents": doc_stats.get("removed_total", 0),
            "removed_active_documents": doc_stats.get("removed_active", 0),
            "removed_deleted_documents": doc_stats.get("removed_deleted", 0),
            "removed_vector_files": removed_vector_files,
        }


def process_user_uploaded_documents(file_paths: List[str], rag_processor: RAGProcessor):
    from src.ingestion.parsers.document_processor import process_uploaded_documents

    processed_documents = process_uploaded_documents(file_paths)
    if not processed_documents:
        return 0
    return rag_processor.process_documents(processed_documents)
