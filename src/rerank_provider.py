import logging
from typing import List, Dict, Any
from abc import ABC, abstractmethod
import requests
import json
from openai import OpenAI

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class RerankProvider(ABC):
    """重排序提供者抽象基类"""
    
    @abstractmethod
    def rerank(self, query: str, documents: List[str], top_k: int = 10) -> List[Dict[str, Any]]:
        """
        重排序文档
        :param query: 查询文本
        :param documents: 待重排序的文档列表
        :param top_k: 返回前k个结果
        :return: 重排序后的结果列表，包含索引、文档和相关性分数
        """
        pass


class AliyunRerankProvider(RerankProvider):
    """
    阿里云重排序提供者
    使用阿里云DashScope的rerank模型
    """
    
    def __init__(self, api_key: str, model_name: str = "gte-rerank", endpoint: str = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-retrieve-rerank", ssl_verify: bool = True, env: str = "development"):
        """
        初始化阿里云重排序提供者
        :param api_key: API密钥
        :param model_name: 模型名称
        :param endpoint: API端点
        :param ssl_verify: 是否验证SSL证书
        :param env: 环境（development/production）
        """
        self.ssl_verify = ssl_verify
        self.endpoint = endpoint  # 保存完整的端点URL
        self.env = env  # 保存环境信息
        # 使用OpenAI客户端用于统一的认证管理
        import httpx
        http_client = httpx.Client(verify=ssl_verify)
        
        # 直接使用提供的endpoint作为base_url
        base_url = endpoint
        
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,  # 直接使用提供的端点作为base_url
            http_client=http_client
        )
        self.model_name = model_name
        self.endpoint = endpoint  # 使用具体的端点URL
        logger.info(f"阿里云重排序提供者初始化完成，模型名称: {self.model_name}, 环境: {self.env}")
    
    def set_ssl_verify(self, ssl_verify: bool):
        """设置SSL验证状态"""
        if self.ssl_verify != ssl_verify:
            # 保存环境信息
            env = self.env
            
            # 关闭现有的HTTP客户端
            if hasattr(self.client, '_client') and hasattr(self.client._client, 'close'):
                self.client._client.close()
            
            # 创建新的HTTP客户端
            import httpx
            http_client = httpx.Client(verify=ssl_verify)
            
            # 直接使用提供的endpoint作为base_url
            base_url = self.endpoint
            
            # 重新创建OpenAI客户端
            self.client = OpenAI(
                api_key=self.client.api_key,
                base_url=base_url,
                http_client=http_client
            )
            
            # 恢复环境信息
            self.env = env
            
            self.ssl_verify = ssl_verify
            logger.info(f"重排序提供者的SSL验证已设置为: {ssl_verify}")
    
    def rerank(self, query: str, documents: List[str], top_k: int = 10) -> List[Dict[str, Any]]:
        """
        使用OpenAI兼容API进行重排序
        :param query: 查询文本
        :param documents: 待重排序的文档列表
        :param top_k: 返回前k个结果
        :return: 重排序后的结果列表
        """
        if not documents:
            return []

        # 预处理：限制文档数量和长度，防止API 400错误
        # 阿里云 gte-rerank 限制单次请求文档数，通常为 10
        MAX_DOCS = 10
        if len(documents) > MAX_DOCS:
            logger.warning(f"待重排文档数量({len(documents)})超过限制({MAX_DOCS})，进行截断")
            documents = documents[:MAX_DOCS]
        
        # 限制单个文档长度，防止总请求体过大
        MAX_DOC_LEN = 1000
        processed_docs = []
        for doc in documents:
            if len(doc) > MAX_DOC_LEN:
                processed_docs.append(doc[:MAX_DOC_LEN] + "...")
            else:
                processed_docs.append(doc)
        documents = processed_docs

        # 记录调用参数
        logger.info(f"调用重排序模型API，参数详情:")
        logger.info(f"  查询文本: {query}")
        logger.info(f"  待排序文档数量: {len(documents)}")
        logger.info(f"  Top-K: {top_k}")
        logger.info(f"  模型名称: {self.model_name}")
        logger.info(f"  基础URL: {self.client.base_url}")
        logger.info(f"  前两个文档预览: {[doc[:100] + '...' if len(doc) > 100 else doc for doc in documents[:2]]}")
        
        try:
            # 使用OpenAI SDK进行重排序
            import json
            
            # 根据环境确定API路径
            api_path = "/reranks" if self.env == "development" else "/rerank"
            
            # 打印将要发送的请求的URL、Headers和Body内容
            base_url_str = str(self.client.base_url).rstrip('/')  # 移除末尾的斜杠
            actual_endpoint = f"{base_url_str}{api_path}"  # 标准OpenAI重排序端点
            logger.info(f"重排序模型API请求详情:")
            logger.info(f"  URL: {actual_endpoint}")
            logger.info(f"  Method: POST")
            logger.info(f"  Headers: {{'Authorization': 'Bearer ***', 'Content-Type': 'application/json'}}")
            logger.info(f"  Request Body: {{'model': '{self.model_name}', 'query': '{query}', 'documents': [...], 'top_n': {top_k}}}")
            
            # 使用标准的OpenAI兼容格式进行重排序
            import httpx
            
            # 构建请求体
            payload = {
                "model": self.model_name,
                "query": query,
                "documents": documents,
                "top_n": top_k
            }
            
            # 发送请求到重排序端点，确保URL正确拼接，避免双斜杠
            base_url_str = str(self.client.base_url).rstrip('/')  # 移除末尾的斜杠
            with httpx.Client(timeout=30.0, verify=self.ssl_verify) as client:
                response = client.post(
                    f"{base_url_str}{api_path}",  # 使用完整的重排序端点，根据环境选择路径
                    headers={
                        "Authorization": f"Bearer {self.client.api_key}",
                        "Content-Type": "application/json"
                    },
                    json=payload
                )
                
                logger.info(f"重排序API调用响应: {response.status_code}")
                
                if response.status_code != 200:
                    logger.error(f"重排序请求失败: {response.status_code}, {response.text}")
                    raise Exception(f"重排序请求失败: {response.status_code}")
                
                result = response.json()
                logger.info(f"重排序API调用成功，响应状态: 成功")
            
            # 记录完整的响应内容
            logger.info(f"重排序API响应数据: {json.dumps(result, ensure_ascii=False, indent=2)}")
            
            # 提取重排序结果
            reranked_results = []
            if 'results' in result:
                for i, item in enumerate(result['results']):
                    index = item.get('index', 0)
                    relevance_score = item.get('relevance_score', 0.0)
                    
                    reranked_results.append({
                        "index": index,
                        "document": documents[index] if index < len(documents) else "",
                        "relevance_score": relevance_score
                    })
                    
                    logger.info(f"  结果 {i+1}: 索引={index}, 相关性分数={relevance_score:.4f}")
            else:
                logger.warning("响应中未找到预期的重排序结果，使用默认排序")
                # 如果API返回格式不符合预期，使用默认排序
                for i, doc in enumerate(documents[:top_k]):
                    reranked_results.append({
                        "index": i,
                        "document": doc,
                        "relevance_score": 1.0 / (i + 1)  # 简单的递减分数
                    })
            
            logger.info(f"重排序完成，返回 {len(reranked_results)} 个结果")
            return reranked_results
            
        except Exception as e:
            logger.error(f"重排序过程中发生错误: {e}")
            # 实现 fail-fast 行为，直接抛出异常
            raise


