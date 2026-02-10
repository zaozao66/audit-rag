import logging
from typing import Dict, Any, Optional, List
from src.llm.providers.llm_provider import LLMProvider

logger = logging.getLogger(__name__)

class IntentRouter:
    """意图路由逻辑处理"""
    
    def __init__(self, llm_provider: Optional[LLMProvider] = None):
        self.llm_provider = llm_provider

    def get_routed_params(self, query: str, default_top_k: int = 5, use_rerank: bool = True, rerank_top_k: int = 10) -> Dict[str, Any]:
        """统一意图识别和参数路由逻辑"""
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
            "rerank_top_k": safe_rerank_top_k
        }
