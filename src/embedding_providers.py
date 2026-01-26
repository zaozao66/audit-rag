import logging
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
    
    def __init__(self, api_key: str, endpoint: str = "https://api.example.com/compatible-mode/v1", model_name: str = "text-embedding-v4"):
        self.api_key = api_key
        self.endpoint = endpoint
        self.model_name = model_name
        self.client = OpenAI(
            api_key=api_key,
            base_url=endpoint
        )
        self.dimension = 1024  # 实际从API返回的维度
        logger.info(f"Text Embedding提供者初始化完成，模型名称: {self.model_name}")
    
    def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        获取文本的嵌入向量
        :param texts: 需要转换的文本列表
        :return: 对应的嵌入向量列表
        """
        # API对批量请求有限制，最多10个项目，所以我们需要分批处理
        batch_size = 10
        all_embeddings = []
        
        try:
            for i in range(0, len(texts), batch_size):
                batch_texts = texts[i:i+batch_size]
                
                # 调用API获取嵌入向量
                response = self.client.embeddings.create(
                    model=self.model_name,
                    input=batch_texts
                )
                
                # 提取嵌入向量
                for data in response.data:
                    all_embeddings.append(data.embedding)
            
            # 更新维度（如果需要）
            if all_embeddings and len(all_embeddings[0]) != self.dimension:
                self.dimension = len(all_embeddings[0])
            
            return all_embeddings
            
        except Exception as e:
            logger.error(f"获取嵌入向量时发生错误: {e}")
            raise