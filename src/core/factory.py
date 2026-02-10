import logging
from typing import Dict, Any, Optional
from src.utils.config_loader import load_config
from src.indexing.vector.embedding_providers import TextEmbeddingProvider
from src.indexing.vector.vector_store import VectorStore
from src.retrieval.rerank.rerank_provider import AliyunRerankProvider
from src.llm.providers.llm_provider import create_llm_provider
from src.core.interfaces import BaseLLM, BaseEmbedder, BaseRetriever

logger = logging.getLogger(__name__)

class RAGFactory:
    """RAG组件工厂类 - 负责集中创建和组装对象"""
    
    @staticmethod
    def create_embedding_provider(config: Dict[str, Any], env: str) -> TextEmbeddingProvider:
        """创建嵌入模型提供者"""
        embed_config = config['embedding_model']
        return TextEmbeddingProvider(
            api_key=embed_config['api_key'],
            endpoint=embed_config['endpoint'],
            model_name=embed_config['model_name'],
            ssl_verify=embed_config.get('ssl_verify', True),
            env=env
        )

    @staticmethod
    def create_rerank_provider(config: Dict[str, Any], env: str) -> Optional[AliyunRerankProvider]:
        """创建重排序提供者"""
        rerank_config = config.get('rerank_model')
        if not rerank_config or not rerank_config.get('api_key'):
            logger.warning("未配置重排序模型，将禁用重排功能")
            return None
            
        return AliyunRerankProvider(
            api_key=rerank_config['api_key'],
            model_name=rerank_config.get('model_name', 'gte-rerank'),
            endpoint=rerank_config.get('endpoint'),
            ssl_verify=rerank_config.get('ssl_verify', True),
            env=env
        )

    @staticmethod
    def create_llm_provider(config: Dict[str, Any]) -> Optional[BaseLLM]:
        """创建LLM提供者"""
        llm_config = config.get('llm_model')
        if not llm_config or not llm_config.get('api_key'):
            logger.warning("未配置LLM模型，将禁用智能功能")
            return None
            
        return create_llm_provider(llm_config)

    @staticmethod
    def create_vector_store(config: Dict[str, Any]) -> VectorStore:
        """创建向量存储"""
        # 维度通常由Embedding模型决定，这里默认1024
        dimension = config.get('embedding_model', {}).get('dimension', 1024)
        return VectorStore(dimension=dimension)
