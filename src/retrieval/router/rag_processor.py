import hashlib
import logging
import os
import re
from collections import defaultdict, deque
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.indexing.graph.graph_builder import GraphBuilder
from src.indexing.graph.graph_retriever import GraphRetriever
from src.indexing.graph.graph_store import GraphStore
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

    def build_contexts_and_citations(self, search_results: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        contexts: List[Dict[str, Any]] = []
        citations: List[Dict[str, Any]] = []

        for idx, res in enumerate(search_results, 1):
            doc = res.get("document", {})
            source_id = f"S{idx}"
            raw_text = doc.get("text", "") or ""
            text_preview = raw_text[:220] + ("..." if len(raw_text) > 220 else "")

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

            citations.append(
                {
                    "source_id": source_id,
                    "doc_id": doc.get("doc_id", ""),
                    "chunk_id": doc.get("chunk_id", ""),
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
            )

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

    def list_graph_nodes(
        self,
        page: int = 1,
        page_size: int = 20,
        node_type: str = None,
        keyword: str = None,
    ) -> Dict[str, Any]:
        self._ensure_graph_store_loaded()

        type_filter = (node_type or "").strip()
        keyword_filter = (keyword or "").strip().lower()

        nodes = []
        for node in self.graph_store.nodes.values():
            if type_filter and node.get("type") != type_filter:
                continue
            if keyword_filter:
                name = str(node.get("name", "")).lower()
                attrs_text = str(node.get("attrs", "")).lower()
                if keyword_filter not in name and keyword_filter not in attrs_text:
                    continue
            nodes.append(node)

        nodes.sort(key=lambda n: (str(n.get("type", "")), str(n.get("name", ""))))
        total = len(nodes)
        start = (page - 1) * page_size
        end = start + page_size

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "nodes": nodes[start:end],
        }

    def list_graph_edges(
        self,
        page: int = 1,
        page_size: int = 20,
        relation: str = None,
        keyword: str = None,
    ) -> Dict[str, Any]:
        self._ensure_graph_store_loaded()

        relation_filter = (relation or "").strip()
        keyword_filter = (keyword or "").strip().lower()

        edges = []
        for source, neighbors in self.graph_store.edges.items():
            source_node = self.graph_store.get_node(source) or {}
            source_name = source_node.get("name", source)
            source_type = source_node.get("type", "")

            for edge in neighbors:
                rel = edge.get("relation", "")
                if relation_filter and rel != relation_filter:
                    continue

                target = edge.get("target")
                target_node = self.graph_store.get_node(target) or {}
                target_name = target_node.get("name", target)
                target_type = target_node.get("type", "")

                if keyword_filter:
                    edge_text = f"{source_name} {source_type} {rel} {target_name} {target_type}".lower()
                    if keyword_filter not in edge_text:
                        continue

                edges.append(
                    {
                        "source": source,
                        "source_name": source_name,
                        "source_type": source_type,
                        "target": target,
                        "target_name": target_name,
                        "target_type": target_type,
                        "relation": rel,
                        "weight": float(edge.get("weight", 1.0)),
                    }
                )

        edges.sort(key=lambda e: (str(e.get("relation", "")), str(e.get("source_name", "")), str(e.get("target_name", ""))))
        total = len(edges)
        start = (page - 1) * page_size
        end = start + page_size

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "edges": edges[start:end],
        }

    def get_graph_subgraph(
        self,
        query: str = None,
        node_ids: List[str] = None,
        hops: int = 2,
        max_nodes: int = 120,
    ) -> Dict[str, Any]:
        self._ensure_graph_store_loaded()

        safe_hops = max(1, min(4, int(hops)))
        safe_max_nodes = max(20, min(300, int(max_nodes)))

        seed_nodes = set()
        for node_id in node_ids or []:
            if node_id in self.graph_store.nodes:
                seed_nodes.add(node_id)

        if query:
            matches = self.graph_store.find_nodes_by_query(query, max_nodes=12)
            for m in matches:
                seed_nodes.add(m["node_id"])

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
                if target in visited:
                    continue
                visited.add(target)
                q.append((target, depth + 1))
                if len(visited) >= safe_max_nodes:
                    break

        nodes = [self.graph_store.nodes[node_id] for node_id in visited if node_id in self.graph_store.nodes]
        nodes.sort(key=lambda n: (str(n.get("type", "")), str(n.get("name", ""))))

        edge_seen = set()
        edges = []
        for source in visited:
            for edge in self.graph_store.neighbors(source):
                target = edge.get("target")
                relation = edge.get("relation", "")
                if target not in visited:
                    continue
                signature = (source, target, relation)
                if signature in edge_seen:
                    continue
                edge_seen.add(signature)
                source_node = self.graph_store.get_node(source) or {}
                target_node = self.graph_store.get_node(target) or {}
                edges.append(
                    {
                        "source": source,
                        "source_name": source_node.get("name", source),
                        "source_type": source_node.get("type", ""),
                        "target": target,
                        "target_name": target_node.get("name", target),
                        "target_type": target_node.get("type", ""),
                        "relation": relation,
                        "weight": float(edge.get("weight", 1.0)),
                    }
                )

        edges.sort(key=lambda e: (str(e.get("relation", "")), str(e.get("source_name", "")), str(e.get("target_name", ""))))

        return {
            "seed_nodes": list(seed_nodes),
            "nodes": nodes,
            "edges": edges,
            "hops": safe_hops,
            "max_nodes": safe_max_nodes,
        }

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
