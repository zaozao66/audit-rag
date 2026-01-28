import logging
from typing import List
from .embedding_providers import EmbeddingProvider

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MockEmbeddingProvider(EmbeddingProvider):
    """
    模拟嵌入提供者 - 用于测试目的
    生成随机向量而不是调用真实API
    """
    
    def __init__(self, dimension: int = 1024):
        self.dimension = dimension
        logger.info(f"Mock Embedding提供者初始化完成，维度: {self.dimension}")
    
    def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        生成模拟的嵌入向量
        :param texts: 需要转换的文本列表
        :return: 模拟的嵌入向量列表
        """
        import numpy as np
        
        # 记录调用参数
        logger.info(f"调用模拟嵌入模型，输入文本数量: {len(texts)}")
        logger.info(f"模拟嵌入模型调用参数详情:")
        logger.info(f"  输入文本内容: {texts}")
        logger.info(f"  向量维度: {self.dimension}")
        
        # 打印模拟请求的URL、Headers和Body内容
        logger.info(f"模拟嵌入模型API请求详情:")
        logger.info(f"  URL: mock://embedding-provider/generate")
        logger.info(f"  Method: MOCK")
        logger.info(f"  Headers: {{'Content-Type': 'application/json', 'X-Mock-Provider': 'True'}}")
        logger.info(f"  Request Body: {{'input': {texts}, 'dimension': {self.dimension}}}")
        
        logger.info(f"生成 {len(texts)} 个文本的模拟嵌入向量")
        
        # 为每个文本生成一个固定维度的随机向量
        # 这里使用文本的哈希值作为种子，确保相同文本产生相同的向量
        embeddings = []
        for i, text in enumerate(texts):
            # 使用文本内容生成一个确定性的伪随机向量
            text_hash = hash(text) % (2 ** 32)
            np.random.seed(text_hash)
            
            # 生成一个标准化的随机向量
            vector = np.random.random(self.dimension).tolist()
            
            # 归一化向量
            norm = sum(x**2 for x in vector) ** 0.5
            normalized_vector = [x/norm for x in vector]
            
            embeddings.append(normalized_vector)
        
        # 记录返回内容
        logger.info(f"模拟嵌入模型API响应数据: 总计向量数={len(embeddings)}")
        for j, emb in enumerate(embeddings):
            logger.info(f"  向量 {j+1}: 维度={len(emb)}, 前5维=[{', '.join([f'{x:.4f}' for x in emb[:5]])}...]")
        
        logger.info(f"成功生成 {len(embeddings)} 个模拟嵌入向量")
        return embeddings