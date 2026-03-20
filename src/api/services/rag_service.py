import logging
import os
import threading
from typing import Any, Dict, Optional, Tuple

from src.core.factory import RAGFactory
from src.retrieval.router.rag_processor import RAGProcessor
from src.utils.config_loader import load_config


class RAGService:
    """Thread-safe RAG processor lifecycle manager with scope isolation."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self._logger = logger or logging.getLogger(__name__)
        self._lock = threading.RLock()
        self._processors: Dict[Tuple[Any, ...], RAGProcessor] = {}

    @staticmethod
    def _normalize_scope(scope: Optional[str]) -> str:
        return str(scope or "").strip().lower()

    @staticmethod
    def _derive_scope_vector_path(base_path: str, scope: str) -> str:
        normalized_scope = str(scope or "").strip().lower()
        if normalized_scope in {"", "audit", "default"}:
            return base_path

        base_dir = os.path.dirname(base_path)
        base_name = os.path.basename(base_path)
        return os.path.join(base_dir, f"{base_name}_{normalized_scope}")

    def _collect_scope_configs(self, config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        raw_scopes = config.get("knowledge_scopes", {})
        if isinstance(raw_scopes, dict) and raw_scopes:
            normalized: Dict[str, Dict[str, Any]] = {}
            for raw_name, raw_cfg in raw_scopes.items():
                scope_name = self._normalize_scope(raw_name)
                if not scope_name:
                    continue
                scope_cfg = dict(raw_cfg or {}) if isinstance(raw_cfg, dict) else {}
                vector_store_path = str(scope_cfg.get("vector_store_path", "") or "").strip()
                if not vector_store_path:
                    legacy_path = str(
                        config.get("vector_store_path", "./data/vector_store_text_embedding")
                    )
                    vector_store_path = self._derive_scope_vector_path(legacy_path, scope_name)
                scope_cfg["vector_store_path"] = vector_store_path
                normalized[scope_name] = scope_cfg
            if normalized:
                return normalized

        legacy_vector_store_path = str(config.get("vector_store_path", "./data/vector_store_text_embedding"))
        return {
            "audit": {"vector_store_path": legacy_vector_store_path},
            "discipline": {"vector_store_path": self._derive_scope_vector_path(legacy_vector_store_path, "discipline")},
        }

    def resolve_scope(self, scope: Optional[str] = None, config: Optional[Dict[str, Any]] = None) -> str:
        effective_config = config or load_config()
        scope_configs = self._collect_scope_configs(effective_config)
        scope_names = list(scope_configs.keys())
        if not scope_names:
            raise ValueError("未配置任何知识域(knowledge_scopes)")

        requested_scope = self._normalize_scope(scope)
        default_scope = self._normalize_scope(effective_config.get("default_scope")) or "audit"
        if default_scope not in scope_configs:
            default_scope = scope_names[0]

        scope_required = bool(effective_config.get("scope_required", False))
        if not requested_scope:
            if scope_required:
                raise ValueError(f"缺少scope参数，可选值: {', '.join(scope_names)}")
            return default_scope

        if requested_scope not in scope_configs:
            raise ValueError(f"不支持的scope: {requested_scope}，可选值: {', '.join(scope_names)}")

        return requested_scope

    def get_scope_config(self, scope: Optional[str], config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        effective_config = config or load_config()
        resolved_scope = self.resolve_scope(scope, config=effective_config)
        scope_configs = self._collect_scope_configs(effective_config)
        return dict(scope_configs.get(resolved_scope, {}))

    @staticmethod
    def _merge_dict(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(base or {})
        for key, value in (override or {}).items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                nested = dict(merged.get(key, {}))
                nested.update(value)
                merged[key] = nested
            else:
                merged[key] = value
        return merged

    def get_processor(
        self,
        scope: Optional[str] = None,
        chunker_type: str = None,
        use_rerank: bool = False,
        use_llm: bool = False,
    ) -> RAGProcessor:
        """Return a scoped processor instance matching current request capabilities."""
        with self._lock:
            config = load_config()
            env = config.get("environment", "development")
            resolved_scope = self.resolve_scope(scope, config=config)
            scope_config = self.get_scope_config(resolved_scope, config=config)
            effective_config = self._merge_dict(config, scope_config)

            chunking_cfg = effective_config.get("chunking", {})
            chunk_size = int(chunking_cfg.get("chunk_size", 512))
            overlap = int(chunking_cfg.get("overlap", 50))
            final_chunker_type = chunker_type or chunking_cfg.get("chunker_type", "smart")
            vector_store_path = str(
                scope_config.get("vector_store_path")
                or effective_config.get("vector_store_path")
                or "./data/vector_store_text_embedding"
            )

            feature_cfg = scope_config.get("features", {}) if isinstance(scope_config.get("features"), dict) else {}
            intent_router_cfg = (
                scope_config.get("intent_router", {})
                if isinstance(scope_config.get("intent_router"), dict)
                else {}
            )
            retrieval_defaults = (
                scope_config.get("retrieval_defaults", {})
                if isinstance(scope_config.get("retrieval_defaults"), dict)
                else {}
            )
            default_retrieval_plan = self._merge_dict(
                retrieval_defaults,
                intent_router_cfg.get("default_retrieval_plan", {})
                if isinstance(intent_router_cfg.get("default_retrieval_plan"), dict)
                else {},
            )
            intent_router_enabled = bool(
                intent_router_cfg.get(
                    "enabled",
                    feature_cfg.get("intent_router", True),
                )
            )
            intent_router_default_intent = str(
                intent_router_cfg.get("default_intent", "comprehensive_query")
            )
            intent_router_fixed_top_k = intent_router_cfg.get("fixed_top_k")
            if intent_router_fixed_top_k is None:
                intent_router_fixed_top_k = scope_config.get("default_top_k")
            intent_router_fixed_doc_types = intent_router_cfg.get(
                "fixed_doc_types",
                scope_config.get("default_doc_types", []),
            )
            if not isinstance(intent_router_fixed_doc_types, list):
                intent_router_fixed_doc_types = []

            processor_key = (
                resolved_scope,
                final_chunker_type,
                bool(use_rerank),
                bool(use_llm),
                vector_store_path,
                intent_router_enabled,
                str(intent_router_default_intent),
                str(intent_router_fixed_top_k),
                ",".join(sorted(str(v) for v in intent_router_fixed_doc_types)),
                str(sorted(default_retrieval_plan.items())),
            )

            processor = self._processors.get(processor_key)
            if processor is None:
                self._logger.info("使用 RAGFactory 初始化处理器: env=%s scope=%s", env, resolved_scope)
                embedding_provider = RAGFactory.create_embedding_provider(effective_config, env)
                llm_provider = RAGFactory.create_llm_provider(effective_config) if use_llm else None
                rerank_provider = RAGFactory.create_rerank_provider(effective_config, env) if use_rerank else None

                processor = RAGProcessor(
                    embedding_provider=embedding_provider,
                    chunk_size=chunk_size,
                    overlap=overlap,
                    vector_store_path=vector_store_path,
                    chunker_type=final_chunker_type,
                    rerank_provider=rerank_provider,
                    llm_provider=llm_provider,
                    scope=resolved_scope,
                    intent_router_enabled=intent_router_enabled,
                    intent_router_default_intent=intent_router_default_intent,
                    intent_router_fixed_top_k=intent_router_fixed_top_k,
                    intent_router_fixed_doc_types=intent_router_fixed_doc_types,
                    intent_router_default_retrieval_plan=default_retrieval_plan,
                )
                self._processors[processor_key] = processor
                self._logger.info(
                    "RAG处理器初始化完成，env=%s scope=%s chunker=%s vector_store=%s",
                    env,
                    resolved_scope,
                    final_chunker_type,
                    vector_store_path,
                )

            return processor
