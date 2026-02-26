"""
LLM提供者 - 用于生成式回答
支持多种LLM提供商（DeepSeek、OpenAI等）
"""

import logging
import json
import re
import httpx
from typing import List, Dict, Any, Optional
from openai import OpenAI

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class LLMProvider:
    """LLM提供者基类"""
    
    def __init__(
        self,
        model_name: str,
        api_key: str,
        endpoint: str = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        ssl_verify: bool = True,
        request_timeout: float = 60.0
    ):
        """
        初始化LLM提供者
        
        :param model_name: 模型名称
        :param api_key: API密钥
        :param endpoint: API端点（可选）
        :param temperature: 温度参数，控制生成随机性
        :param max_tokens: 最大生成token数
        :param ssl_verify: 是否验证SSL证书
        """
        self.model_name = model_name
        self.api_key = api_key
        self.endpoint = endpoint
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.ssl_verify = ssl_verify
        self.request_timeout = request_timeout
        
        # 初始化OpenAI客户端
        client_kwargs = {
            "api_key": api_key,
        }
        
        if endpoint:
            client_kwargs["base_url"] = endpoint
        
        # 配置SSL验证
        if not ssl_verify:
            # 创建自定义 httpx 客户端，禁用 SSL 验证
            http_client = httpx.Client(verify=False)
            client_kwargs["http_client"] = http_client
            logger.warning(f"LLM客户端已禁用SSL验证 (ssl_verify=False)")
            
        self.client = OpenAI(**client_kwargs)
        
        logger.info(
            f"LLM提供者初始化完成 - 模型: {model_name}, 端点: {endpoint or 'default'}, SSL验证: {ssl_verify}, 超时: {request_timeout}s"
        )
    
    def generate_answer(
        self,
        query: str,
        contexts: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        conversation_messages: Optional[List[Dict[str, str]]] = None,
        conversation_summary: str = "",
        standalone_query: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        基于检索结果生成回答
        
        :param query: 用户问题
        :param contexts: 检索到的上下文列表
        :param system_prompt: 系统提示词（可选）
        :return: 包含回答和元信息的字典
        """
        try:
            # 构建上下文文本
            context_text = self._build_context_text(contexts)
            
            # 构建提示词
            if system_prompt is None:
                system_prompt = self._get_default_system_prompt()
            
            conversation_text = self._build_conversation_text(conversation_messages or [])
            user_prompt = self._build_user_prompt(
                query=query,
                context_text=context_text,
                conversation_text=conversation_text,
                conversation_summary=conversation_summary,
                standalone_query=standalone_query,
            )
            
            # 构建请求消息
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            
            # 打印调用请求信息
            logger.info("=" * 60)
            logger.info("调用大模型请求详情:")
            logger.info(f"模型: {self.model_name}")
            logger.info(f"端点: {self.endpoint or 'default'}")
            logger.info(f"温度: {self.temperature}")
            logger.info(f"最大tokens: {self.max_tokens}")
            logger.info(f"SSL验证: {self.ssl_verify}")
            logger.info(f"\n系统提示词:\n{system_prompt}")
            logger.info(f"\n用户输入:\n{user_prompt}")
            logger.info("=" * 60)
            
            # 调用LLM生成回答
            logger.info(f"正在调用LLM生成回答...")
            logger.info(f"请求URL: {self.endpoint or 'https://api.openai.com/v1'}")
            logger.info(f"请求参数: model={self.model_name}, temperature={self.temperature}, max_tokens={self.max_tokens}")
            
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    timeout=self.request_timeout
                )
            except Exception as api_error:
                logger.error("=" * 60)
                logger.error("LLM API调用失败详情:")
                logger.error(f"错误类型: {type(api_error).__name__}")
                logger.error(f"错误信息: {str(api_error)}")
                logger.error(f"请求端点: {self.endpoint or 'default'}")
                logger.error(f"模型名称: {self.model_name}")
                
                # 尝试获取更详细的错误信息
                if hasattr(api_error, 'response'):
                    logger.error(f"HTTP状态码: {getattr(api_error.response, 'status_code', 'N/A')}")
                    logger.error(f"响应内容: {getattr(api_error.response, 'text', 'N/A')}")
                if hasattr(api_error, '__cause__'):
                    logger.error(f"根本原因: {api_error.__cause__}")
                
                logger.error("=" * 60)
                raise
            
            answer = response.choices[0].message.content
            
            # 打印响应结果
            logger.info("=" * 60)
            logger.info("LLM响应结果:")
            logger.info(f"\n生成的回答:\n{answer}")
            logger.info(f"\nToken使用统计:")
            logger.info(f"  - 输入tokens: {response.usage.prompt_tokens}")
            logger.info(f"  - 输出tokens: {response.usage.completion_tokens}")
            logger.info(f"  - 总计tokens: {response.usage.total_tokens}")
            logger.info("=" * 60)
            
            # 构建返回结果
            result = {
                "answer": answer,
                "query": query,
                "contexts_used": len(contexts),
                "model": self.model_name,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
            }
            
            logger.info(f"LLM回答生成完成，tokens使用: {response.usage.total_tokens}")
            
            return result
            
        except Exception as e:
            logger.error(f"LLM生成回答失败: {e}")
            raise

    def stream_generate_answer(
        self,
        query: str,
        contexts: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        conversation_messages: Optional[List[Dict[str, str]]] = None,
        conversation_summary: str = "",
        standalone_query: Optional[str] = None,
    ):
        """
        基于检索结果流式生成回答

        :param query: 用户问题
        :param contexts: 检索到的上下文列表
        :param system_prompt: 系统提示词（可选）
        :yield: {"type": "delta", "content": "..."} 或 {"type": "done", ...}
        """
        try:
            context_text = self._build_context_text(contexts)
            if system_prompt is None:
                system_prompt = self._get_default_system_prompt()
            conversation_text = self._build_conversation_text(conversation_messages or [])
            user_prompt = self._build_user_prompt(
                query=query,
                context_text=context_text,
                conversation_text=conversation_text,
                conversation_summary=conversation_summary,
                standalone_query=standalone_query,
            )

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            logger.info("=" * 60)
            logger.info("调用大模型流式请求详情:")
            logger.info(f"模型: {self.model_name}")
            logger.info(f"端点: {self.endpoint or 'default'}")
            logger.info(f"温度: {self.temperature}")
            logger.info(f"最大tokens: {self.max_tokens}")
            logger.info(f"SSL验证: {self.ssl_verify}")
            logger.info("=" * 60)

            stream = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=True,
                timeout=self.request_timeout
            )

            completion_tokens = 0
            for chunk in stream:
                choice = chunk.choices[0] if chunk.choices else None
                if not choice:
                    continue

                delta = getattr(choice, "delta", None)
                content = getattr(delta, "content", None) if delta else None
                if content:
                    completion_tokens += 1
                    yield {"type": "delta", "content": content}

                if getattr(choice, "finish_reason", None):
                    break

            yield {
                "type": "done",
                "model": self.model_name,
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": completion_tokens,
                    "total_tokens": completion_tokens
                }
            }

        except Exception as e:
            logger.error(f"LLM流式生成回答失败: {e}")
            raise

    def detect_intent(self, query: str) -> Dict[str, Any]:
        """
        识别用户查询意图
        
        :param query: 用户问题
        :return: 意图详情字典
        """
        intent_prompt = f"""你是一个专业的审计RAG系统路由助手。请分析用户问题并输出JSON。

意图分类：
- regulation_query: 查询法律法规、公司制度、管理办法、合规要求等。
- audit_query: 查询特定审计报告的内容、审计发现的具体问题、整改情况等。
- audit_issue: 查询以往审计发现的问题库、类似问题的整改要求、审计问题台账等。
- audit_analysis: 对审计报告进行宏观汇总、风险趋势分析、跨报告的TOP问题总结。
- comprehensive_query: 同时涉及制度要求和审计实操的对比，或无法简单归类的复杂问题。

必须返回以下JSON格式，不要包含任何其他文字：
{{
  "intent": "意图名称",
  "reason": "分类的逻辑理由",
  "suggested_top_k": 建议检索的片段数量(5-30之间的整数),
  "doc_types": ["建议搜索的文档类型列表，可选: internal_regulation, external_regulation, internal_report, external_report, audit_issue"],
  "retrieval_mode": "vector/hybrid/graph 之一",
  "use_graph": true 或 false,
  "graph_hops": 1-4,
  "graph_top_k": 5-40,
  "hybrid_alpha": 0-1 之间的小数（越大越偏向向量）
}}

用户问题: {query}"""

        try:
            logger.info(f"正在识别用户意图: {query[:30]}...")
            
            # 构建意图识别请求详情打印
            logger.info("=" * 60)
            logger.info("意图识别请求详情:")
            logger.info(f"模型: {self.model_name}")
            logger.info(f"端点: {self.endpoint or 'default'}")
            logger.info(f"Prompt:\n{intent_prompt}")
            logger.info("=" * 60)

            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": "你是一个严格只返回JSON格式的后端助手。"},
                        {"role": "user", "content": intent_prompt}
                    ],
                    temperature=0.1,
                    timeout=self.request_timeout
                )
            except Exception as api_error:
                logger.error("=" * 60)
                logger.error("意图识别API调用失败:")
                logger.error(f"错误类型: {type(api_error).__name__}")
                logger.error(f"错误信息: {str(api_error)}")
                logger.error(f"请求端点: {self.endpoint or 'default'}")
                
                # 尝试获取更详细的错误信息
                if hasattr(api_error, 'response'):
                    logger.error(f"HTTP状态码: {getattr(api_error.response, 'status_code', 'N/A')}")
                    logger.error(f"响应内容: {getattr(api_error.response, 'text', 'N/A')}")
                if hasattr(api_error, '__cause__'):
                    logger.error(f"根本原因: {api_error.__cause__}")
                
                logger.error("=" * 60)
                raise
            
            raw_content = response.choices[0].message.content.strip()
            logger.info("-" * 60)
            logger.info(f"意图识别原始响应:\n{raw_content}")
            logger.info("-" * 60)

            content = raw_content
            # 处理可能的Markdown代码块
            if content.startswith("```json"):
                content = content.split("```json")[1].split("```")[0].strip()
            elif content.startswith("```"):
                content = content.split("```")[1].split("```")[0].strip()
            
            intent_result = json.loads(content)
            
            # 补全缺失字段
            if 'intent' not in intent_result:
                intent_result['intent'] = 'comprehensive_query'
            if 'suggested_top_k' not in intent_result:
                intent_result['suggested_top_k'] = 5
            if 'reason' not in intent_result:
                intent_result['reason'] = 'LLM未提供具体理由'
            if 'retrieval_mode' not in intent_result:
                intent_result['retrieval_mode'] = 'hybrid'
            if 'use_graph' not in intent_result:
                intent_result['use_graph'] = True
            if 'graph_hops' not in intent_result:
                intent_result['graph_hops'] = 2
            if 'graph_top_k' not in intent_result:
                intent_result['graph_top_k'] = 12
            if 'hybrid_alpha' not in intent_result:
                intent_result['hybrid_alpha'] = 0.65
                
            logger.info(f"识别到意图: {intent_result['intent']} (理由: {intent_result['reason']}, 建议top_k: {intent_result['suggested_top_k']})")
            return intent_result
            
        except Exception as e:
            logger.error(f"意图识别解析失败: {e}. 响应内容: {content if 'content' in locals() else 'None'}")
            return {
                "intent": "comprehensive_query",
                "reason": f"解析失败降级: {str(e)}",
                "suggested_top_k": 5,
                "doc_types": ["internal_regulation", "external_regulation", "audit_report", "audit_issue"],
                "retrieval_mode": "hybrid",
                "use_graph": True,
                "graph_hops": 2,
                "graph_top_k": 12,
                "hybrid_alpha": 0.65
            }

    def rewrite_query(
        self,
        query: str,
        recent_messages: Optional[List[Dict[str, str]]] = None,
        conversation_summary: str = "",
    ) -> str:
        """Rewrite follow-up questions into standalone queries."""
        question = (query or "").strip()
        if not question:
            return ""

        recent_messages = recent_messages or []
        if not recent_messages and not conversation_summary:
            return question

        prompt = f"""请把用户当前问题改写为“可独立检索”的单句问题。
要求：
1) 保留原问题意图，不扩展新事实
2) 补全代词指代（如“这个/它/上面提到的”）
3) 输出仅一行改写后的问题，不要解释

历史摘要:
{conversation_summary or '(无)'}

最近对话:
{self._build_conversation_text(recent_messages)}

当前问题:
{question}
"""

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": "你是检索查询改写助手，只输出改写后的问题。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=256,
                timeout=self.request_timeout,
            )
            rewritten = (response.choices[0].message.content or "").strip()
            rewritten = rewritten.strip("` \n\t\"'")
            return rewritten or question
        except Exception as e:
            logger.warning("Query改写失败，降级使用原问题: %s", e)
            return question

    def route_retrieval(
        self,
        query: str,
        recent_messages: Optional[List[Dict[str, str]]] = None,
        has_last_contexts: bool = False,
    ) -> Dict[str, str]:
        """
        Decide whether to skip retrieval, reuse previous docs, or run full retrieval.
        Returns: {"decision": "...", "reason": "..."}
        """
        question = (query or "").strip()
        if not question:
            return {"decision": "no_retrieval", "reason": "空查询"}

        heuristic = self._heuristic_route(question, has_last_contexts=has_last_contexts)
        if heuristic["decision"] != "full_retrieval":
            return heuristic

        recent_text = self._build_conversation_text(recent_messages or [])
        prompt = f"""请根据当前问题判断检索策略，必须返回JSON：
{{
  "decision": "no_retrieval | reuse_docs | full_retrieval",
  "reason": "简短理由"
}}

规则：
- no_retrieval: 寒暄、确认、纯改写/润色，不需要知识库事实
- reuse_docs: 对上轮结果追问/展开，优先复用上轮文档
- full_retrieval: 新主题、事实性问答、需要新证据

当前问题: {question}
最近对话: {recent_text or '(无)'}
可复用上轮文档: {has_last_contexts}
"""
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": "你是检索路由助手，只输出JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=180,
                timeout=self.request_timeout,
            )
            payload = self._extract_json_block((response.choices[0].message.content or "").strip())
            data = json.loads(payload)
            decision = str(data.get("decision", "full_retrieval")).strip().lower()
            if decision not in {"no_retrieval", "reuse_docs", "full_retrieval"}:
                decision = "full_retrieval"
            if decision == "reuse_docs" and not has_last_contexts:
                decision = "full_retrieval"
            reason = str(data.get("reason", "")).strip() or "LLM路由结果"
            return {"decision": decision, "reason": reason}
        except Exception as e:
            logger.warning("检索路由失败，降级到规则路由: %s", e)
            return heuristic

    def summarize_messages(
        self,
        recent_messages: Optional[List[Dict[str, str]]] = None,
        previous_summary: str = "",
    ) -> str:
        """Summarize conversation memory to control context length."""
        recent_messages = recent_messages or []
        if not recent_messages:
            return previous_summary.strip()

        prompt = f"""请把下面的会话总结成简洁记忆，供后续问答使用。
输出要求：
- 3~6条要点
- 保留关键实体、时间、约束条件、用户目标
- 不要编造

已有摘要:
{previous_summary or '(无)'}

最近对话:
{self._build_conversation_text(recent_messages)}
"""
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": "你是对话摘要助手。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=320,
                timeout=self.request_timeout,
            )
            summary = (response.choices[0].message.content or "").strip()
            return summary or previous_summary.strip()
        except Exception as e:
            logger.warning("会话摘要失败，使用简化摘要: %s", e)
            lines = [previous_summary.strip()] if previous_summary.strip() else []
            for msg in recent_messages[-6:]:
                role = "用户" if msg.get("role") == "user" else "助手"
                lines.append(f"- {role}: {msg.get('content', '')[:120]}")
            return "\n".join(line for line in lines if line).strip()

    def _heuristic_route(self, query: str, has_last_contexts: bool) -> Dict[str, str]:
        light_chat = {"谢谢", "好的", "明白了", "了解", "收到", "ok", "OK"}
        if query in light_chat:
            return {"decision": "no_retrieval", "reason": "寒暄或确认语句"}

        no_retrieval_keywords = ("改写", "润色", "翻译", "总结一下这句话", "帮我优化表达")
        if any(k in query for k in no_retrieval_keywords):
            return {"decision": "no_retrieval", "reason": "语言处理请求"}

        follow_up_markers = ("这个", "这个问题", "上面", "刚才", "前面", "继续", "展开", "再细化", "它", "这些")
        if has_last_contexts and any(m in query for m in follow_up_markers):
            return {"decision": "reuse_docs", "reason": "疑似追问上轮内容"}

        return {"decision": "full_retrieval", "reason": "默认走完整检索"}

    def _extract_json_block(self, text: str) -> str:
        if not text:
            return "{}"
        cleaned = text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0].strip()
            return cleaned
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```", 1)[1].split("```", 1)[0].strip()
            return cleaned
        match = re.search(r"\\{[\\s\\S]*\\}", cleaned)
        if match:
            return match.group(0)
        return cleaned
    
    def _build_context_text(self, contexts: List[Dict[str, Any]]) -> str:
        """
        将检索结果构建为上下文文本
        
        :param contexts: 检索结果列表
        :return: 格式化的上下文文本
        """
        context_parts = []
        
        for i, ctx in enumerate(contexts, 1):
            text = ctx.get('text', '')
            title = ctx.get('title', '')
            filename = ctx.get('filename', '')
            doc_type = ctx.get('doc_type', '')
            score = ctx.get('score', 0)
            source_id = ctx.get('source_id', f'S{i}')
            
            # 构建单个上下文，附带稳定的来源ID，便于回答中引用 [Sx]
            if filename:
                context_part = f"[{source_id}] 来源: {filename}"
            elif title:
                context_part = f"[{source_id}] 来源: {title}"
            else:
                context_part = f"[{source_id}] 来源: 参考资料{i}"
            
            # 添加标题（如果和文件名不同）
            if title and title != filename:
                context_part += f"\n标题: {title}"
            if doc_type:
                context_part += f"\n类型: {doc_type}"
            context_part += f"\n相关度: {score:.4f}"
            context_part += f"\n内容:\n{text}\n"
            
            context_parts.append(context_part)
        
        return "\n".join(context_parts)
    
    def _get_default_system_prompt(self) -> str:
        """
        获取默认系统提示词
        
        :return: 系统提示词
        """
        return """你是一个专业的审计和合规助手，擅长根据法规制度和审计报告来回答问题。

请严格遵循：
1. 只能基于给定参考资料回答，不要编造来源
2. 每条关键结论后必须添加来源标记，格式为 [S1]、[S2]
3. 来源标记必须来自参考资料中的来源ID，不能凭空创建
4. 如果资料不足，请明确说明“未在参考资料中找到充分依据”
5. 回答结构清晰、专业、可执行"""

    def _build_conversation_text(self, messages: List[Dict[str, str]], max_items: int = 8) -> str:
        rows: List[str] = []
        for msg in (messages or [])[-max_items:]:
            role = msg.get("role", "")
            if role not in {"user", "assistant", "system"}:
                continue
            role_label = "用户" if role == "user" else ("助手" if role == "assistant" else "系统")
            content = str(msg.get("content", "")).strip()
            if not content:
                continue
            rows.append(f"{role_label}: {content}")
        return "\n".join(rows)
    
    def _build_user_prompt(
        self,
        query: str,
        context_text: str,
        conversation_text: str = "",
        conversation_summary: str = "",
        standalone_query: Optional[str] = None,
    ) -> str:
        """
        构建用户提示词
        
        :param query: 用户问题
        :param context_text: 上下文文本
        :return: 用户提示词
        """
        rewrite_line = f"\n检索改写问题: {standalone_query}" if standalone_query else ""
        summary_block = f"\n历史摘要:\n{conversation_summary}\n" if conversation_summary else "\n历史摘要:\n(无)\n"
        convo_block = f"\n最近对话:\n{conversation_text}\n" if conversation_text else "\n最近对话:\n(无)\n"

        return f"""请基于以下参考资料回答问题。

{context_text}
{summary_block}
{convo_block}

问题: {query}
{rewrite_line}

输出要求：
- 在结论句后追加来源标记，如：XXX。[S1]
- 可以同时引用多个来源，如：[S1][S3]
- 不要输出不存在的来源编号
- 不要省略来源标记
- 如果参考资料为空，只能基于对话历史回答且明确说明“本回答未使用知识库证据”"""


def create_llm_provider(config: Dict[str, Any]) -> LLMProvider:
    """
    根据配置创建LLM提供者
    
    :param config: LLM配置字典
    :return: LLM提供者实例
    """
    provider = config.get('provider', 'deepseek')
    model_name = config.get('model_name', 'deepseek-chat')
    api_key = config.get('api_key')
    endpoint = config.get('endpoint')
    temperature = config.get('temperature', 0.7)
    max_tokens = config.get('max_tokens', 2000)
    ssl_verify = config.get('ssl_verify', True)
    request_timeout = config.get('request_timeout', 60.0)
    
    if not api_key:
        raise ValueError("LLM API密钥未配置")
    
    logger.info(f"创建LLM提供者: {provider}, 模型: {model_name}")
    
    return LLMProvider(
        model_name=model_name,
        api_key=api_key,
        endpoint=endpoint,
        temperature=temperature,
        max_tokens=max_tokens,
        ssl_verify=ssl_verify,
        request_timeout=request_timeout
    )
