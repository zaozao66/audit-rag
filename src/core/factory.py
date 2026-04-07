import logging
from typing import Dict, Any, Optional
from src.utils.config_loader import load_config
from src.indexing.vector.embedding_providers import TextEmbeddingProvider
from src.indexing.vector.vector_store import VectorStore
from src.audio.providers.base import BaseTTSProvider
from src.audio.providers.cosyvoice_provider import CosyVoiceProvider
from src.audio.providers.melo_tts_provider import MeloTTSProvider
from src.audio.providers.nucc_tts_provider import NUCCTTSProvider
from src.audio.providers.qwen_tts_provider import QwenTTSProvider
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
            env=env,
            request_timeout=embed_config.get('request_timeout', 30.0),
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
    def create_tts_provider(config: Dict[str, Any]) -> BaseTTSProvider:
        """创建TTS提供者"""
        audio_cfg = config.get("audio", {}) if isinstance(config.get("audio"), dict) else {}
        tts_cfg = audio_cfg.get("tts", {}) if isinstance(audio_cfg.get("tts"), dict) else {}
        provider_name = str(tts_cfg.get("provider", "qwen")).strip().lower() or "qwen"

        providers_cfg = tts_cfg.get("providers", {}) if isinstance(tts_cfg.get("providers"), dict) else {}
        provider_cfg = providers_cfg.get(provider_name, {}) if isinstance(providers_cfg.get(provider_name), dict) else {}

        fallback_llm_cfg = config.get("llm_model", {}) if isinstance(config.get("llm_model"), dict) else {}
        merged_cfg = {
            "endpoint": provider_cfg.get("endpoint") or tts_cfg.get("endpoint") or fallback_llm_cfg.get("endpoint"),
            "api_key": provider_cfg.get("api_key") or tts_cfg.get("api_key") or fallback_llm_cfg.get("api_key"),
            "model": provider_cfg.get("model") or tts_cfg.get("model") or "qwen3-tts-flash-2025-11-27",
            "ssl_verify": provider_cfg.get("ssl_verify", tts_cfg.get("ssl_verify", True)),
            "request_timeout": provider_cfg.get("request_timeout", tts_cfg.get("request_timeout", 20.0)),
            "path": provider_cfg.get("path", tts_cfg.get("path", "/tts")),
            "default_voice": provider_cfg.get("default_voice", tts_cfg.get("default_voice", "Cherry")),
            "task_type": provider_cfg.get("task_type") or tts_cfg.get("task_type"),
            "language": provider_cfg.get("language") or tts_cfg.get("language"),
            "instructions": provider_cfg.get("instructions") or tts_cfg.get("instructions"),
        }

        if provider_name == "qwen":
            return QwenTTSProvider(merged_cfg, logger=logger)
        if provider_name in {"nucc", "nucc_tts"}:
            return NUCCTTSProvider(merged_cfg, logger=logger)
        if provider_name == "cosyvoice":
            return CosyVoiceProvider(merged_cfg, logger=logger)
        if provider_name in {"melotts", "melo"}:
            return MeloTTSProvider(merged_cfg, logger=logger)
        raise ValueError(f"不支持的TTS provider: {provider_name}")

    @staticmethod
    def create_vector_store(config: Dict[str, Any]) -> VectorStore:
        """创建向量存储"""
        # 维度通常由Embedding模型决定，这里默认1024
        dimension = config.get('embedding_model', {}).get('dimension', 1024)
        return VectorStore(dimension=dimension)
