import faiss
import numpy as np
import json
import logging
from typing import List, Dict, Any
import pickle
import os
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


class AliyunTextEmbeddingProvider(EmbeddingProvider):
    """
    阿里云Text Embedding提供者 - 使用text-embedding-v4模型
    通过OpenAI SDK调用
    """
    
    def __init__(self, api_key: str, endpoint: str = "https://dashscope.aliyuncs.com/compatible-mode/v1", model_name: str = "text-embedding-v4"):
        self.api_key = api_key
        self.endpoint = endpoint
        self.model_name = model_name
        self.client = OpenAI(
            api_key=api_key,
            base_url=endpoint
        )
        self.dimension = 1536  # text-embedding-v4的维度
        logger.info(f"阿里云Text Embedding提供者初始化完成，模型名称: {self.model_name}")
    
    def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        获取文本的嵌入向量
        :param texts: 需要转换的文本列表
        :return: 对应的嵌入向量列表
        """
        logger.info(f"开始生成嵌入向量，文本数量: {len(texts)}")
        
        try:
            # 调用阿里云API获取嵌入向量
            response = self.client.embeddings.create(
                model=self.model_name,
                input=texts
            )
            
            # 提取嵌入向量
            embeddings = []
            for data in response.data:
                embeddings.append(data.embedding)
            
            logger.info(f"嵌入向量生成完成，维度: {len(embeddings[0]) if embeddings else 0}")
            return embeddings
            
        except Exception as e:
            logger.error(f"获取嵌入向量时发生错误: {e}")
            raise


class DocumentChunker:
    """文档分块器 - 将长文档分割为较小的块以适应模型输入限制"""
    
    def __init__(self, chunk_size: int = 512, overlap: int = 50):
        """
        初始化文档分块器
        :param chunk_size: 每个块的最大字符数
        :param overlap: 相邻块之间的重叠字符数（保持上下文连续性）
        """
        self.chunk_size = chunk_size
        self.overlap = overlap
        logger.info(f"文档分块器初始化完成，块大小: {chunk_size}, 重叠: {overlap}")
    
    def chunk_text(self, text: str) -> List[Dict[str, Any]]:
        """
        将单个文本分割成块
        :param text: 输入的长文本
        :return: 分块后的文本列表，每个元素包含文本内容和元数据
        """
        logger.info(f"开始分割文本，总长度: {len(text)} 字符")
        
        # 如果文本长度小于等于块大小，直接返回整个文本作为一个块
        if len(text) <= self.chunk_size:
            logger.info("文本长度小于块大小，无需分割")
            return [{
                'text': text,
                'start_pos': 0,
                'end_pos': len(text),
                'chunk_id': 'chunk_0'
            }]
        
        chunks = []
        start = 0
        chunk_count = 0
        
        # 循环分割文本
        while start < len(text):
            end = start + self.chunk_size
            
            # 确保不超出文本长度
            if end > len(text):
                end = len(text)
            
            chunk_text = text[start:end]
            
            # 添加到结果列表
            chunks.append({
                'text': chunk_text,
                'start_pos': start,
                'end_pos': end,
                'chunk_id': f'chunk_{chunk_count}'
            })
            
            logger.debug(f"创建块 #{chunk_count}: 位置 {start}-{end}, 长度 {len(chunk_text)}")
            
            # 检查是否到达文本末尾
            if start + self.chunk_size >= len(text):
                logger.info(f"文本分割完成，共创建 {len(chunks)} 个块")
                break
                
            # 计算下一个块的起始位置（考虑重叠）
            start = end - self.overlap if self.overlap < self.chunk_size else start + self.chunk_size
            chunk_count += 1
        
        return chunks
    
    def chunk_documents(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        分割多个文档
        :param documents: 文档列表
        :return: 分块后的文档列表
        """
        logger.info(f"开始分割 {len(documents)} 个文档")
        all_chunks = []
        
        for doc_idx, document in enumerate(documents):
            logger.info(f"正在处理文档 {doc_idx + 1}/{len(documents)}")
            
            text = document.get('text', '')
            metadata = {k: v for k, v in document.items() if k != 'text'}
            
            logger.info(f"文档 {doc_idx + 1} 文本长度: {len(text)} 字符")
            
            # 分割单个文档
            chunks = self.chunk_text(text)
            
            # 合并文档元数据和块元数据
            for chunk in chunks:
                chunk_data = {
                    'text': chunk['text'],
                    'doc_id': document.get('doc_id', f'doc_{doc_idx}'),
                    'chunk_id': chunk['chunk_id'],
                    'start_pos': chunk['start_pos'],
                    'end_pos': chunk['end_pos'],
                    **metadata  # 合并原始文档的元数据
                }
                all_chunks.append(chunk_data)
        
        logger.info(f"所有文档分割完成，共生成 {len(all_chunks)} 个文本块")
        return all_chunks


class VectorStore:
    """向量存储类 - 使用Faiss进行高效向量相似性搜索"""
    
    def __init__(self, dimension: int, metric_type: int = faiss.METRIC_INNER_PRODUCT):
        """
        初始化向量存储
        :param dimension: 向量的维度
        :param metric_type: 相似性度量类型
        """
        self.dimension = dimension
        self.metric_type = metric_type
        # 使用Faiss的内积索引（适合归一化向量的余弦相似度）
        self.index = faiss.IndexFlatIP(dimension)
        self.documents = []  # 存储文档信息
        self.is_normalized = False  # 标记向量是否已归一化
        logger.info(f"向量存储初始化完成，维度: {dimension}")
    
    def add_embeddings(self, embeddings: List[List[float]], documents: List[Dict[str, Any]]):
        """
        添加嵌入向量到向量库
        :param embeddings: 嵌入向量列表
        :param documents: 对应的文档信息列表
        """
        logger.info(f"开始添加 {len(embeddings)} 个嵌入向量到向量库")
        
        # 验证嵌入向量数量与文档数量是否一致
        if len(embeddings) != len(documents):
            error_msg = f"嵌入向量数量({len(embeddings)})与文档数量({len(documents)})不一致"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # 将嵌入向量转换为numpy数组
        logger.info("转换嵌入向量为numpy数组...")
        embeddings_array = np.array(embeddings).astype('float32')
        
        # 如果使用内积作为距离度量，需要对向量进行L2归一化
        if self.metric_type == faiss.METRIC_INNER_PRODUCT and not self.is_normalized:
            logger.info("对向量进行L2归一化...")
            faiss.normalize_L2(embeddings_array)
            self.is_normalized = True
        
        # 添加到Faiss索引
        logger.info("添加向量到Faiss索引...")
        self.index.add(embeddings_array)
        
        # 保存文档信息
        logger.info("保存文档信息...")
        self.documents.extend(documents)
        
        logger.info(f"成功添加 {len(embeddings)} 个向量和文档到向量库")
    
    def search(self, query_embedding: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
        """
        搜索最相似的向量
        :param query_embedding: 查询向量
        :param top_k: 返回前k个结果
        :return: 包含相似文档和相似度分数的结果列表
        """
        logger.info(f"开始搜索最相似的 {top_k} 个文档")
        
        # 将查询向量转换为numpy数组
        query_array = np.array([query_embedding]).astype('float32')
        
        # 如果使用内积度量，需要对查询向量也进行归一化
        if self.metric_type == faiss.METRIC_INNER_PRODUCT and self.is_normalized:
            logger.info("对查询向量进行L2归一化...")
            faiss.normalize_L2(query_array)
        
        # 执行Faiss搜索
        logger.info("执行Faiss相似性搜索...")
        scores, indices = self.index.search(query_array, top_k)
        
        logger.info(f"搜索完成，找到 {len(indices[0])} 个结果")
        
        results = []
        # 处理搜索结果
        for i in range(min(len(indices[0]), len(self.documents))):
            idx = indices[0][i]
            if idx < len(self.documents) and idx != -1:
                result = {
                    'document': self.documents[idx],
                    'score': float(scores[0][i])  # 相似度分数
                }
                results.append(result)
        
        logger.info(f"返回 {len(results)} 个搜索结果")
        return results
    
    def save(self, filepath: str):
        """
        保存向量库到文件
        :param filepath: 保存路径（不包含扩展名）
        """
        logger.info(f"开始保存向量库到 {filepath}")
        
        # 保存Faiss索引
        logger.info("保存Faiss索引...")
        faiss.write_index(self.index, f"{filepath}.index")
        
        # 保存文档信息
        logger.info("保存文档信息...")
        with open(f"{filepath}.docs", 'wb') as f:
            pickle.dump(self.documents, f)
        
        logger.info(f"向量库已成功保存到 {filepath}")
    
    def load(self, filepath: str):
        """
        从文件加载向量库
        :param filepath: 加载路径（不包含扩展名）
        """
        logger.info(f"开始从 {filepath} 加载向量库")
        
        # 加载Faiss索引
        logger.info("加载Faiss索引...")
        self.index = faiss.read_index(f"{filepath}.index")
        
        # 加载文档信息
        logger.info("加载文档信息...")
        with open(f"{filepath}.docs", 'rb') as f:
            self.documents = pickle.load(f)
        
        logger.info(f"向量库已从 {filepath} 成功加载")


class RAGProcessor:
    """RAG处理器主类 - 协调整个RAG流程"""
    
    def __init__(self, embedding_provider: EmbeddingProvider, chunk_size: int = 512, overlap: int = 50):
        """
        初始化RAG处理器
        :param embedding_provider: 嵌入提供者
        :param chunk_size: 文本块大小
        :param overlap: 块间重叠大小
        """
        self.embedding_provider = embedding_provider
        self.chunker = DocumentChunker(chunk_size=chunk_size, overlap=overlap)
        self.vector_store = None
        self.dimension = None  # 将在第一次调用时确定
        logger.info("RAG处理器初始化完成")
    
    def process_documents(self, documents: List[Dict[str, Any]]):
        """
        处理文档：分块、生成嵌入向量、存储到向量库
        :param documents: 文档列表
        :return: 生成的文本块数量
        """
        logger.info(f"开始处理文档流程，文档数量: {len(documents)}")
        
        # 步骤1: 分块
        logger.info("步骤1: 开始文档分块...")
        chunks = self.chunker.chunk_documents(documents)
        logger.info(f"步骤1完成: 共生成 {len(chunks)} 个文本块")
        
        if len(chunks) == 0:
            logger.warning("没有找到任何文本块，处理结束")
            return 0
        
        # 步骤2: 提取文本用于嵌入
        logger.info("步骤2: 提取文本用于嵌入向量生成...")
        texts_for_embedding = [chunk['text'] for chunk in chunks]
        logger.info(f"步骤2完成: 准备了 {len(texts_for_embedding)} 个文本片段")
        
        # 步骤3: 获取嵌入向量
        logger.info("步骤3: 开始生成嵌入向量...")
        embeddings = self.embedding_provider.get_embeddings(texts_for_embedding)
        logger.info(f"步骤3完成: 生成了 {len(embeddings)} 个嵌入向量")
        
        # 确定嵌入维度
        if self.dimension is None:
            self.dimension = len(embeddings[0]) if embeddings else 1536
            logger.info(f"检测到嵌入维度: {self.dimension}")
        
        # 步骤4: 创建向量库
        logger.info("步骤4: 创建向量存储...")
        self.vector_store = VectorStore(dimension=self.dimension)
        
        # 步骤5: 添加到向量库
        logger.info("步骤5: 添加向量和文档到向量库...")
        self.vector_store.add_embeddings(embeddings, chunks)
        
        logger.info("文档处理流程完成！")
        return len(chunks)
    
    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        搜索相关文档
        :param query: 查询文本
        :param top_k: 返回前k个结果
        :return: 搜索结果列表
        """
        logger.info(f"开始搜索，查询: '{query}', 返回前 {top_k} 个结果")
        
        # 检查向量库是否存在
        if not self.vector_store:
            error_msg = "向量库不存在，请先处理文档以构建向量库"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # 获取查询的嵌入向量
        logger.info("获取查询文本的嵌入向量...")
        query_embeddings = self.embedding_provider.get_embeddings([query])
        query_embedding = query_embeddings[0]
        logger.info(f"查询向量生成完成，维度: {len(query_embedding)}")
        
        # 执行搜索
        logger.info("执行向量相似性搜索...")
        results = self.vector_store.search(query_embedding, top_k=top_k)
        logger.info(f"搜索完成，找到 {len(results)} 个结果")
        
        return results
    
    def save_vector_store(self, filepath: str):
        """保存向量库"""
        logger.info(f"开始保存向量库到 {filepath}")
        
        if not self.vector_store:
            error_msg = "没有可保存的向量库"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        self.vector_store.save(filepath)
        logger.info(f"向量库已成功保存到 {filepath}")
    
    def load_vector_store(self, filepath: str):
        """加载向量库"""
        logger.info(f"开始从 {filepath} 加载向量库")
        
        self.vector_store = VectorStore(dimension=self.dimension or 1536)
        self.vector_store.load(filepath)
        logger.info(f"向量库已从 {filepath} 成功加载")


def load_config(config_path: str = "./config.json") -> dict:
    """加载配置文件"""
    logger.info(f"开始加载配置文件: {config_path}")
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    logger.info(f"配置文件加载完成，嵌入模型提供商: {config['embedding_model']['provider']}")
    return config


def create_aliyun_embedding_provider(config: dict) -> AliyunTextEmbeddingProvider:
    """根据配置创建阿里云嵌入提供者"""
    logger.info("创建阿里云Text Embedding提供者...")
    
    embedding_config = config['embedding_model']
    api_key = embedding_config['api_key']
    endpoint = embedding_config['endpoint']
    model_name = embedding_config['model_name']
    
    provider = AliyunTextEmbeddingProvider(
        api_key=api_key,
        endpoint=endpoint,
        model_name=model_name
    )
    
    logger.info(f"阿里云Text Embedding提供者创建完成，模型: {model_name}")
    return provider


# 使用示例
if __name__ == "__main__":
    logger.info("=== 开始运行阿里云Text Embedding RAG系统演示 ===")
    
    try:
        # 加载配置
        logger.info("加载配置文件...")
        config = load_config()
        
        # 创建阿里云嵌入提供者
        logger.info("创建阿里云嵌入提供者...")
        embedding_provider = create_aliyun_embedding_provider(config)
        
        # 获取配置参数
        chunk_size = config['chunking']['chunk_size']
        overlap = config['chunking']['overlap']
        logger.info(f"使用配置参数 - 块大小: {chunk_size}, 重叠: {overlap}")
        
        # 创建RAG处理器
        logger.info("创建RAG处理器...")
        rag_processor = RAGProcessor(
            embedding_provider=embedding_provider,
            chunk_size=chunk_size,
            overlap=overlap
        )
        
        # 准备示例文档
        logger.info("准备示例文档...")
        documents = [
            {
                'doc_id': 'doc_1',
                'title': 'RAG技术介绍',
                'text': 'RAG（Retrieval-Augmented Generation）是一种结合检索和生成的技术，通过检索相关信息来增强生成模型的能力。这种技术在问答系统和文本生成任务中表现优异。',
                'source': 'example_source_1'
            },
            {
                'doc_id': 'doc_2',
                'title': '阿里云通义千问介绍',
                'text': '通义千问是阿里云开发的大规模语言模型，能够回答问题、创作文字、表达观点、玩游戏等。该模型具有强大的语言理解和生成能力。',
                'source': 'example_source_2'
            }
        ]
        
        # 处理文档
        logger.info("开始处理示例文档...")
        num_chunks = rag_processor.process_documents(documents)
        logger.info(f"文档处理完成，共生成 {num_chunks} 个文本块")
        
        # 执行搜索
        logger.info("开始执行搜索示例...")
        query = "什么是RAG技术"
        results = rag_processor.search(query, top_k=config['search']['top_k'])
        
        logger.info(f"\n查询: {query}")
        logger.info("搜索结果:")
        for i, result in enumerate(results, 1):
            logger.info(f"{i}. 相似度分数: {result['score']:.4f}")
            logger.info(f"   文本: {result['document']['text'][:100]}...")
            logger.info(f"   来源: {result['document'].get('source', 'Unknown')}")
            logger.info('')
        
        # 保存向量库
        logger.info("保存向量库...")
        rag_processor.save_vector_store("./vector_store_aliyun_text_embedding")
        
        logger.info("=== 阿里云Text Embedding RAG系统演示完成 ===")
        
        print("\n系统提示:")
        print("✅ 系统已成功连接阿里云text-embedding-v4服务")
        print("✅ 所有RAG流程正常工作：文档处理、向量生成、相似性搜索")
        print("✅ 使用阿里云远程API进行向量嵌入")
        
    except Exception as e:
        logger.error(f"系统运行出错: {e}")
        import traceback
        traceback.print_exc()