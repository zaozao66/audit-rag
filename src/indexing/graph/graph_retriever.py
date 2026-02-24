from collections import defaultdict, deque
from typing import Any, Dict, List, Optional

from src.core.schemas import SearchResult
from src.indexing.graph.graph_store import GraphStore


class GraphRetriever:
    """Graph traversal retriever that ranks chunk nodes by proximity to query entities."""

    def __init__(self, graph_store: GraphStore, documents: Optional[List[Dict[str, Any]]] = None):
        self.graph_store = graph_store
        self.documents_by_chunk_id: Dict[str, Dict[str, Any]] = {}
        if documents:
            self.refresh_documents(documents)

    def refresh_documents(self, documents: List[Dict[str, Any]]):
        self.documents_by_chunk_id = {}
        for d in documents:
            chunk_id = d.get("chunk_id")
            if chunk_id:
                self.documents_by_chunk_id[str(chunk_id)] = d

    def search(
        self,
        query: str,
        top_k: int = 8,
        doc_types: Optional[List[str]] = None,
        hops: int = 2,
        max_seed_nodes: int = 24,
    ) -> List[SearchResult]:
        seeds = self.graph_store.find_nodes_by_query(query, max_nodes=max_seed_nodes)
        if not seeds:
            return []

        allow_chunks = self.graph_store.iter_chunk_nodes(doc_types=doc_types)
        chunk_scores = defaultdict(float)

        for seed in seeds:
            seed_id = seed["node_id"]
            seed_score = float(seed["score"])
            self._expand(seed_id, seed_score, hops, allow_chunks, chunk_scores)

        ranked = sorted(chunk_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

        results: List[SearchResult] = []
        for chunk_node_id, score in ranked:
            node = self.graph_store.get_node(chunk_node_id)
            if not node:
                continue

            chunk_id = node.get("attrs", {}).get("chunk_id")
            doc = self.documents_by_chunk_id.get(str(chunk_id), {})
            if not doc:
                continue

            results.append(
                SearchResult(
                    text=doc.get("text", ""),
                    score=float(score),
                    filename=doc.get("filename"),
                    doc_type=doc.get("doc_type"),
                    title=doc.get("title"),
                    metadata=doc,
                )
            )

        return results

    def _expand(
        self,
        seed_id: str,
        seed_score: float,
        hops: int,
        allow_chunks,
        chunk_scores,
    ):
        q = deque([(seed_id, 0)])
        seen_depth = {seed_id: 0}

        while q:
            current, depth = q.popleft()
            node = self.graph_store.get_node(current)
            if not node:
                continue

            if node.get("type") == "chunk":
                if not allow_chunks or current in allow_chunks:
                    chunk_scores[current] += seed_score / float(depth + 1)

            if depth >= hops:
                continue

            for edge in self.graph_store.neighbors(current):
                nxt = edge.get("target")
                if not nxt:
                    continue
                next_depth = depth + 1
                best = seen_depth.get(nxt)
                if best is not None and best <= next_depth:
                    continue
                seen_depth[nxt] = next_depth
                q.append((nxt, next_depth))
