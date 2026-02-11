import logging
import threading
from typing import Optional

from src.core.factory import RAGFactory
from src.retrieval.router.rag_processor import RAGProcessor
from src.utils.config_loader import load_config


class RAGService:
    """Thread-safe RAG processor lifecycle manager."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self._logger = logger or logging.getLogger(__name__)
        self._lock = threading.RLock()
        self._processor: Optional[RAGProcessor] = None

    def get_processor(self, chunker_type: str = None, use_rerank: bool = False, use_llm: bool = False) -> RAGProcessor:
        """Return a processor instance matching current request capabilities."""
        with self._lock:
            current_use_rerank = self._processor is not None and self._processor.rerank_provider is not None
            current_use_llm = self._processor is not None and self._processor.llm_provider is not None

            if self._processor is not None:
                type_mismatch = chunker_type is not None and self._processor.chunker_type != chunker_type
                rerank_mismatch = current_use_rerank != use_rerank
                llm_mismatch = current_use_llm != use_llm
                if type_mismatch or rerank_mismatch or llm_mismatch:
                    self._processor = None

            if self._processor is None:
                self._logger.info("使用 RAGFactory 初始化处理器...")
                config = load_config()
                env = config.get('environment', 'development')

                embedding_provider = RAGFactory.create_embedding_provider(config, env)
                llm_provider = RAGFactory.create_llm_provider(config) if use_llm else None
                rerank_provider = RAGFactory.create_rerank_provider(config, env) if use_rerank else None

                chunk_size = config.get('chunking', {}).get('chunk_size', 512)
                overlap = config.get('chunking', {}).get('overlap', 50)
                vector_store_path = config.get('vector_store_path', './data/vector_store_text_embedding')
                final_chunker_type = chunker_type or config.get('chunking', {}).get('chunker_type', 'smart')

                self._processor = RAGProcessor(
                    embedding_provider=embedding_provider,
                    chunk_size=chunk_size,
                    overlap=overlap,
                    vector_store_path=vector_store_path,
                    chunker_type=final_chunker_type,
                    rerank_provider=rerank_provider,
                    llm_provider=llm_provider,
                )
                self._logger.info("RAG处理器初始化完成，环境: %s", env)

            return self._processor
