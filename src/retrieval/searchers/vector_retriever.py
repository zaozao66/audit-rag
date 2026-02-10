import logging
from typing import List, Dict, Any, Optional
from src.core.interfaces import BaseRetriever
from src.core.schemas import SearchResult
from src.indexing.vector.vector_store import VectorStore
from src.indexing.vector.embedding_providers import EmbeddingProvider

logger = logging.getLogger(__name__)

class VectorRetriever(BaseRetriever):
    """向量检索器实现"""
    
    def __init__(self, vector_store: VectorStore, embedding_provider: EmbeddingProvider):
        self.vector_store = vector_store
        self.embedding_provider = embedding_provider

    def search(self, query: str, top_k: int = 5, doc_types: List[str] = None, titles: List[str] = None, **kwargs) -> List[SearchResult]:
        """执行向量搜索"""
        # 1. 获取嵌入向量
        query_embeddings = self.embedding_provider.get_embeddings([query])
        query_embedding = query_embeddings[0]
        
        # 2. 从向量库搜索
        raw_results = self.vector_store.search(
            query_embedding, 
            top_k=top_k, 
            doc_types=doc_types, 
            titles=titles
        )
        
        # 3. 转换为标准 SearchResult 对象
        formatted_results = []
        for res in raw_results:
            doc = res['document']
            formatted_results.append(SearchResult(
                text=doc.get('text', ''),
                score=res.get('score', 0.0),
                filename=doc.get('filename'),
                doc_type=doc.get('doc_type'),
                title=doc.get('title'),
                metadata=doc  # 保留原始元数据
            ))
            
        return formatted_results
