import json
import os
from typing import Any, Dict, List, Optional, Set


class GraphStore:
    """Simple property graph store backed by JSON."""

    def __init__(self):
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.edges: Dict[str, List[Dict[str, Any]]] = {}

    def clear(self):
        self.nodes = {}
        self.edges = {}

    def add_node(self, node_id: str, node_type: str, name: str, attrs: Optional[Dict[str, Any]] = None):
        if node_id not in self.nodes:
            self.nodes[node_id] = {
                "id": node_id,
                "type": node_type,
                "name": name,
                "attrs": attrs or {},
            }
        elif attrs:
            self.nodes[node_id]["attrs"].update(attrs)

    def add_edge(
        self,
        source: str,
        target: str,
        relation: str,
        weight: float = 1.0,
        bidirectional: bool = False,
        reverse_relation: Optional[str] = None,
        attrs: Optional[Dict[str, Any]] = None,
    ):
        if source not in self.nodes or target not in self.nodes:
            return

        self.edges.setdefault(source, []).append(
            {
                "target": target,
                "relation": relation,
                "weight": float(weight),
                "attrs": attrs or {},
            }
        )

        if bidirectional:
            self.edges.setdefault(target, []).append(
                {
                    "target": source,
                    "relation": reverse_relation or relation,
                    "weight": float(weight),
                    "attrs": attrs or {},
                }
            )

    def neighbors(self, node_id: str) -> List[Dict[str, Any]]:
        return self.edges.get(node_id, [])

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        return self.nodes.get(node_id)

    def save(self, filepath: str):
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        payload = {
            "nodes": self.nodes,
            "edges": self.edges,
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

    def load(self, filepath: str):
        with open(filepath, "r", encoding="utf-8") as f:
            payload = json.load(f)
        self.nodes = payload.get("nodes", {})
        self.edges = payload.get("edges", {})

    def exists(self, filepath: str) -> bool:
        return os.path.exists(filepath)

    def find_nodes_by_query(self, query: str, max_nodes: int = 24) -> List[Dict[str, Any]]:
        query = (query or "").strip().lower()
        if not query:
            return []

        tokens = [t for t in _extract_query_tokens(query) if len(t) >= 2]
        scored: List[Dict[str, Any]] = []

        for node in self.nodes.values():
            node_type = node.get("type")
            if node_type in ("chunk", "document"):
                continue

            name = str(node.get("name", "")).lower()
            if not name:
                continue

            score = 0.0
            if name in query:
                score += 2.0

            for token in tokens:
                if token in name:
                    score += 1.0

            if score > 0:
                scored.append({"node_id": node["id"], "score": score})

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:max_nodes]

    def iter_chunk_nodes(self, doc_types: Optional[List[str]] = None) -> Set[str]:
        allow_doc_types = set(doc_types or [])
        chunk_nodes: Set[str] = set()
        for node_id, node in self.nodes.items():
            if node.get("type") != "chunk":
                continue
            if allow_doc_types:
                node_doc_type = node.get("attrs", {}).get("doc_type")
                if node_doc_type not in allow_doc_types:
                    continue
            chunk_nodes.add(node_id)
        return chunk_nodes

    def get_stats(self) -> Dict[str, Any]:
        edge_count = sum(len(v) for v in self.edges.values())
        by_type: Dict[str, int] = {}
        for node in self.nodes.values():
            t = node.get("type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1

        return {
            "nodes": len(self.nodes),
            "edges": edge_count,
            "by_type": by_type,
        }


def _extract_query_tokens(query: str) -> List[str]:
    buf: List[str] = []
    cur = []
    for ch in query:
        if ch.isalnum() or ("\u4e00" <= ch <= "\u9fff"):
            cur.append(ch)
        else:
            if cur:
                buf.append("".join(cur))
                cur = []
    if cur:
        buf.append("".join(cur))
    return buf
