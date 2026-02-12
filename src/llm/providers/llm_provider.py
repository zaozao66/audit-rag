"""
LLM提供者 - 用于生成式回答
支持多种LLM提供商（DeepSeek、OpenAI等）
"""

import logging
import json
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
        system_prompt: Optional[str] = None
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
            
            user_prompt = self._build_user_prompt(query, context_text)
            
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
        system_prompt: Optional[str] = None
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
            user_prompt = self._build_user_prompt(query, context_text)

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
  "doc_types": ["建议搜索的文档类型列表，可选: internal_regulation, external_regulation, internal_report, external_report, audit_issue"]
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
                
            logger.info(f"识别到意图: {intent_result['intent']} (理由: {intent_result['reason']}, 建议top_k: {intent_result['suggested_top_k']})")
            return intent_result
            
        except Exception as e:
            logger.error(f"意图识别解析失败: {e}. 响应内容: {content if 'content' in locals() else 'None'}")
            return {
                "intent": "comprehensive_query",
                "reason": f"解析失败降级: {str(e)}",
                "suggested_top_k": 5,
                "doc_types": ["internal_regulation", "external_regulation", "audit_report", "audit_issue"]
            }
    
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
    
    def _build_user_prompt(self, query: str, context_text: str) -> str:
        """
        构建用户提示词
        
        :param query: 用户问题
        :param context_text: 上下文文本
        :return: 用户提示词
        """
        return f"""请基于以下参考资料回答问题。

{context_text}

问题: {query}

输出要求：
- 在结论句后追加来源标记，如：XXX。[S1]
- 可以同时引用多个来源，如：[S1][S3]
- 不要输出不存在的来源编号
- 不要省略来源标记"""


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
