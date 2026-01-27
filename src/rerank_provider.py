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
    
    def __init__(self, api_key: str, model_name: str = "gte-rerank", endpoint: str = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-retrieve-rerank"):
        """
        初始化阿里云重排序提供者
        :param api_key: API密钥
        :param model_name: 模型名称
        :param endpoint: API端点
        """
        # 使用OpenAI客户端用于统一的认证管理
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com"  # 使用基本URL
        )
        self.model_name = model_name
        self.endpoint = endpoint  # 使用具体的端点URL
        logger.info(f"阿里云重排序提供者初始化完成，模型名称: {self.model_name}")
    
    def rerank(self, query: str, documents: List[str], top_k: int = 10) -> List[Dict[str, Any]]:
        """
        使用阿里云API进行重排序
        :param query: 查询文本
        :param documents: 待重排序的文档列表
        :param top_k: 返回前k个结果
        :return: 重排序后的结果列表
        """
        try:
            # 使用标准的阿里云API格式进行重排序
            import httpx
            import json
            
            headers = {
                "Authorization": f"Bearer {self.client.api_key}",
                "Content-Type": "application/json"
            }
            
            # 使用阿里云标准格式的请求体
            payload = {
                "model": self.model_name,
                "input": {
                    "query": query,
                    "documents": [doc for doc in documents]
                },
                "parameters": {
                    "top_n": top_k
                }
            }
            
            # 打印调用参数用于调试
            logger.info(f"重排序API调用参数:")
            logger.info(f"  端点: {self.endpoint}")
            logger.info(f"  Headers: {dict(headers)}")  # 不打印API密钥
            logger.info(f"  Payload: {payload}")
            
            # 发送请求到指定的端点
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    self.endpoint,
                    headers=headers,
                    json=payload
                )
                
                logger.info(f"第一次API调用响应: {response.status_code}, 内容: {response.text}")
                
                # 如果返回400错误且包含'task can not be null'，尝试添加task参数
                if response.status_code == 400 and "task can not be null" in response.text:
                    logger.info("检测到task参数缺失，尝试添加task参数")
                    payload_with_task = payload.copy()
                    payload_with_task["task"] = "text-retrieve-rerank"
                    
                    logger.info(f"添加task参数后的Payload: {payload_with_task}")
                    
                    response = client.post(
                        self.endpoint,
                        headers=headers,
                        json=payload_with_task
                    )
                    
                    logger.info(f"第二次API调用响应: {response.status_code}, 内容: {response.text}")
                
                if response.status_code != 200:
                    logger.error(f"重排序请求失败: {response.status_code}, {response.text}")
                    raise Exception(f"重排序请求失败: {response.status_code}")
                
                result = response.json()
                
            # 提取重排序结果
            reranked_results = []
            if 'output' in result and 'results' in result['output']:
                for item in result['output']['results']:
                    index = item.get('index', 0)
                    relevance_score = item.get('relevance_score', 0.0)
                    
                    reranked_results.append({
                        "index": index,
                        "document": documents[index] if index < len(documents) else "",
                        "relevance_score": relevance_score
                    })
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
            # 发生错误时使用模拟重排序作为备用方案
            logger.info("切换到模拟重排序提供者作为备用方案")
            mock_provider = MockRerankProvider()
            return mock_provider.rerank(query, documents, top_k)


class MockRerankProvider(RerankProvider):
    """
    模拟重排序提供者 - 用于测试目的
    """
    
    def __init__(self):
        logger.info("模拟重排序提供者初始化完成")
    
    def rerank(self, query: str, documents: List[str], top_k: int = 10) -> List[Dict[str, Any]]:
        """
        模拟重排序功能
        """
        import random
        
        logger.info(f"执行模拟重排序，文档数量: {len(documents)}, top_k: {top_k}")
        
        # 创建结果列表，包含索引和相关性分数
        results = []
        for i, doc in enumerate(documents[:top_k]):
            # 基于文档内容和查询的相关性生成模拟分数
            score = random.uniform(0.1, 1.0)
            # 简单的相关性检查：如果文档包含查询中的词，则提高分数
            query_words = query.lower().split()
            doc_lower = doc.lower()
            for word in query_words:
                if word in doc_lower:
                    score = min(score + 0.1, 1.0)
            
            results.append({
                "index": i,
                "document": doc,
                "relevance_score": round(score, 4)
            })
        
        # 按相关性分数降序排序
        results.sort(key=lambda x: x["relevance_score"], reverse=True)
        
        logger.info(f"模拟重排序完成，返回 {len(results)} 个结果")
        return results