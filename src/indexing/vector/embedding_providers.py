import logging
import ssl
import httpx
from typing import List
from abc import ABC, abstractmethod
from openai import OpenAI

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """嵌入提供者抽象基类"""
    
    @abstractmethod
    def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        获取文本的嵌入向量
        :param texts: 文本列表
        :return: 嵌入向量列表
        """
        pass


class TextEmbeddingProvider(EmbeddingProvider):
    """
    Text Embedding提供者 - 使用text-embedding-v4模型
    通过OpenAI SDK调用
    """
    
    def __init__(self, api_key: str, endpoint: str = "https://api.example.com/compatible-mode/v1", model_name: str = "text-embedding-v4", ssl_verify: bool = True, env: str = "development"):
        self.api_key = api_key
        self.endpoint = endpoint
        self.model_name = model_name
        self.ssl_verify = ssl_verify
        self.env = env  # 存储环境信息
        
        # 直接使用提供的endpoint作为base_url
        base_url = endpoint
        
        # 创建HTTP客户端，支持SSL验证控制
        http_client = httpx.Client(verify=ssl_verify)
        
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client
        )
        self.dimension = 1024  # 实际从API返回的维度
        logger.info(f"Text Embedding提供者初始化完成，模型名称: {self.model_name}, 环境: {self.env}, Base URL: {self.client.base_url}")
    
    def set_ssl_verify(self, ssl_verify: bool):
        """设置SSL验证状态"""
        if self.ssl_verify != ssl_verify:
            # 保存环境信息
            env = self.env
            
            # 关闭现有的HTTP客户端
            if hasattr(self.client, '_client') and hasattr(self.client._client, 'close'):
                self.client._client.close()
            
            # 创建新的HTTP客户端
            http_client = httpx.Client(verify=ssl_verify)
            
            # 直接使用提供的endpoint作为base_url
            base_url = self.endpoint
            
            # 重新创建OpenAI客户端
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=base_url,
                http_client=http_client
            )
            
            # 恢复环境信息
            self.env = env
            
            self.ssl_verify = ssl_verify
            logger.info(f"SSL验证已设置为: {ssl_verify}, Base URL: {self.client.base_url}")
    
    def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        获取文本的嵌入向量
        :param texts: 需要转换的文本列表
        :return: 对应的嵌入向量列表
        """
        # 使用实例变量中的环境信息
        env = self.env
        
        # API对批量请求有限制，最多10个项目，所以我们需要分批处理
        batch_size = 10
        all_embeddings = []
        
        try:
            for i in range(0, len(texts), batch_size):
                batch_texts = texts[i:i+batch_size]
                
                # OpenAI兼容的API端点始终需要添加embeddings后缀
                actual_endpoint = f"{self.client.base_url}/embeddings"
                
                # 记录完整的调用参数
                logger.info(f"调用嵌入模型API: {actual_endpoint}, 模型: {self.model_name}, 批次大小: {len(batch_texts)}, 环境: {env}")
                logger.info(f"嵌入模型API调用参数详情:")
                logger.info(f"  基础URL: {self.client.base_url}")
                logger.info(f"  端点: {actual_endpoint}")
                logger.info(f"  模型名称: {self.model_name}")
                logger.info(f"  输入文本数量: {len(batch_texts)}")
                logger.info(f"  输入文本内容: {batch_texts}")
                
                # 打印将要发送的请求的URL、Headers和Body内容
                logger.info(f"嵌入模型API请求详情:")
                logger.info(f"  URL: {actual_endpoint}")
                logger.info(f"  Method: POST")
                # 由于使用OpenAI SDK，我们不能直接访问headers，但可以推断它们
                logger.info(f"  Headers: {{'Authorization': 'Bearer ***', 'Content-Type': 'application/json'}}")
                logger.info(f"  Request Body: {{'model': '{self.model_name}', 'input': {batch_texts}}}")
                
                # 调用API获取嵌入向量
                response = self.client.embeddings.create(
                    model=self.model_name,
                    input=batch_texts
                )
                
                # 记录完整的响应内容
                logger.info(f"嵌入模型API调用成功，响应状态: 成功, 向量数量: {len(response.data)}")
                
                # 提取嵌入向量
                for j, data in enumerate(response.data):
                    all_embeddings.append(data.embedding)
                    logger.info(f"  响应数据项 {j+1}: index={data.index}, embedding_length={len(data.embedding)}")
            
            # 更新维度（如果需要）
            if all_embeddings and len(all_embeddings[0]) != self.dimension:
                self.dimension = len(all_embeddings[0])
            
            logger.info(f"嵌入向量获取完成，总计向量数: {len(all_embeddings)}")
            return all_embeddings
            
        except Exception as e:
            logger.error(f"获取嵌入向量时发生错误: {e}")
            raise