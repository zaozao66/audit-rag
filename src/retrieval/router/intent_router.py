import logging
from typing import Dict, Any, Optional, List
from src.llm.providers.llm_provider import LLMProvider

logger = logging.getLogger(__name__)

class IntentRouter:
    """意图路由逻辑处理"""
    
    def __init__(self, llm_provider: Optional[LLMProvider] = None):
        self.llm_provider = llm_provider

    def get_routed_params(
        self,
        query: str,
        default_top_k: int = 5,
        use_rerank: bool = True,
        rerank_top_k: int = 10,
        retrieval_overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """统一意图识别和参数路由逻辑（含 GraphRAG 检索参数）"""
        intent_info = {"intent": "comprehensive_query", "suggested_top_k": default_top_k, "reason": "默认路由"}
        
        if self.llm_provider:
            try:
                intent_info = self.llm_provider.detect_intent(query)
            except Exception as e:
                logger.warning(f"意图识别失败，使用默认路由: {e}")
        
        intent = intent_info.get('intent', 'comprehensive_query')
        current_top_k = intent_info.get('suggested_top_k', default_top_k)
        
        # 汇总分析意图强化
        if intent == 'audit_analysis':
            current_top_k = max(current_top_k, 20)
            
        # 文档类型映射
        current_doc_types = intent_info.get('doc_types', None)
        if current_doc_types and 'audit_report' in current_doc_types:
            current_doc_types.remove('audit_report')
            current_doc_types.extend(['internal_report', 'external_report'])
            current_doc_types = list(set(current_doc_types))

        retrieval_plan = self._default_retrieval_plan_by_intent(intent)
        retrieval_plan.update(self._parse_retrieval_plan_from_llm(intent_info))

        if retrieval_overrides:
            # API 显式参数优先级最高
            retrieval_plan.update({k: v for k, v in retrieval_overrides.items() if v is not None})

        retrieval_plan = self._sanitize_retrieval_plan(retrieval_plan)

        # 重排序策略安全限制
        current_use_rerank = use_rerank
        safe_rerank_top_k = rerank_top_k
        if current_top_k > 10:
            if current_top_k >= 20 or intent == 'audit_analysis':
                current_use_rerank = False
            else:
                safe_rerank_top_k = 10
        elif current_top_k <= 5:
            safe_rerank_top_k = min(10, current_top_k * 2)

        return {
            "intent": intent,
            "reason": intent_info.get('reason', ''),
            "top_k": current_top_k,
            "doc_types": current_doc_types,
            "use_rerank": current_use_rerank,
            "rerank_top_k": safe_rerank_top_k,
            "use_graph": retrieval_plan["use_graph"],
            "retrieval_mode": retrieval_plan["retrieval_mode"],
            "graph_top_k": retrieval_plan["graph_top_k"],
            "graph_hops": retrieval_plan["graph_hops"],
            "hybrid_alpha": retrieval_plan["hybrid_alpha"],
        }

    def _default_retrieval_plan_by_intent(self, intent: str) -> Dict[str, Any]:
        # 默认采用 hybrid，避免完全图检索导致召回不稳定
        plan = {
            "use_graph": True,
            "retrieval_mode": "hybrid",
            "graph_top_k": 12,
            "graph_hops": 2,
            "hybrid_alpha": 0.65,
        }

        if intent == "regulation_query":
            plan.update({"graph_top_k": 10, "graph_hops": 1, "hybrid_alpha": 0.75})
        elif intent == "audit_query":
            plan.update({"graph_top_k": 12, "graph_hops": 2, "hybrid_alpha": 0.65})
        elif intent == "audit_issue":
            plan.update({"graph_top_k": 16, "graph_hops": 2, "hybrid_alpha": 0.58})
        elif intent == "audit_analysis":
            plan.update({"retrieval_mode": "graph", "graph_top_k": 24, "graph_hops": 3, "hybrid_alpha": 0.45})
        elif intent == "comprehensive_query":
            plan.update({"graph_top_k": 14, "graph_hops": 2, "hybrid_alpha": 0.6})

        return plan

    def _parse_retrieval_plan_from_llm(self, intent_info: Dict[str, Any]) -> Dict[str, Any]:
        plan = {}

        if "use_graph" in intent_info:
            plan["use_graph"] = bool(intent_info.get("use_graph"))
        if "retrieval_mode" in intent_info:
            plan["retrieval_mode"] = str(intent_info.get("retrieval_mode", "")).lower()
        if "graph_top_k" in intent_info:
            plan["graph_top_k"] = intent_info.get("graph_top_k")
        if "graph_hops" in intent_info:
            plan["graph_hops"] = intent_info.get("graph_hops")
        if "hybrid_alpha" in intent_info:
            plan["hybrid_alpha"] = intent_info.get("hybrid_alpha")

        return plan

    def _sanitize_retrieval_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        mode = str(plan.get("retrieval_mode", "hybrid")).lower()
        if mode not in ("vector", "hybrid", "graph"):
            mode = "hybrid"

        if mode in ("graph", "hybrid"):
            use_graph = True
        else:
            use_graph = False

        try:
            graph_top_k = int(plan.get("graph_top_k", 12))
        except (TypeError, ValueError):
            graph_top_k = 12
        graph_top_k = max(5, min(40, graph_top_k))

        try:
            graph_hops = int(plan.get("graph_hops", 2))
        except (TypeError, ValueError):
            graph_hops = 2
        graph_hops = max(1, min(4, graph_hops))

        try:
            hybrid_alpha = float(plan.get("hybrid_alpha", 0.65))
        except (TypeError, ValueError):
            hybrid_alpha = 0.65
        hybrid_alpha = max(0.0, min(1.0, hybrid_alpha))

        return {
            "use_graph": use_graph,
            "retrieval_mode": mode,
            "graph_top_k": graph_top_k,
            "graph_hops": graph_hops,
            "hybrid_alpha": hybrid_alpha,
        }
