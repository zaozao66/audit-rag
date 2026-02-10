from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class Document:
    """原始文档对象"""
    doc_id: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    filename: Optional[str] = None
    doc_type: Optional[str] = None

@dataclass
class Chunk:
    """文档分块对象"""
    chunk_id: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    vector: Optional[List[float]] = None
    doc_id: Optional[str] = None

@dataclass
class SearchResult:
    """检索结果对象"""
    text: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    filename: Optional[str] = None
    doc_type: Optional[str] = None
    title: Optional[str] = None
