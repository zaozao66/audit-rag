import logging
from typing import List, Dict, Any
from vector_store import VectorStore
from document_chunker import DocumentChunker
from embedding_providers import EmbeddingProvider

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


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
        # 步骤1: 分块
        chunks = self.chunker.chunk_documents(documents)
        
        if len(chunks) == 0:
            logger.warning("没有找到任何文本块，处理结束")
            return 0
        
        # 显示分割统计信息
        logger.info(f"文档分割完成，共生成 {len(chunks)} 个文本块")
        boundary_types = {}
        for chunk in chunks:
            boundary_type = chunk.get('semantic_boundary', 'unknown')
            boundary_types[boundary_type] = boundary_types.get(boundary_type, 0) + 1
        
        logger.info(f"分割类型统计: {dict(boundary_types)}")
        
        # 询问用户是否需要查看所有分块信息
        logger.info(f"文档分割完成，共生成 {len(chunks)} 个文本块")
        show_all = input("是否显示所有分块内容？(y/N): ").lower().startswith('y')
        if show_all:
            logger.info("所有文本块内容:")
            for i, chunk in enumerate(chunks):
                logger.info(f"  块 {i+1} ({chunk.get('semantic_boundary', 'unknown')}): {chunk['text']}")
        else:
            logger.info("前5个文本块预览:")
            for i, chunk in enumerate(chunks[:5]):
                preview = chunk['text'][:100] + "..." if len(chunk['text']) > 100 else chunk['text']
                logger.info(f"  块 {i+1} ({chunk.get('semantic_boundary', 'unknown')}): {preview}")
        
        # 步骤2: 提取文本用于嵌入
        texts_for_embedding = [chunk['text'] for chunk in chunks]
        
        # 步骤3: 获取嵌入向量
        embeddings = self.embedding_provider.get_embeddings(texts_for_embedding)
        
        # 确定嵌入维度
        if self.dimension is None:
            self.dimension = len(embeddings[0]) if embeddings else 1024
        
        # 步骤4: 创建向量库
        self.vector_store = VectorStore(dimension=self.dimension)
        
        # 步骤5: 添加到向量库
        self.vector_store.add_embeddings(embeddings, chunks)
        
        return len(chunks)
    
    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        搜索相关文档
        :param query: 查询文本
        :param top_k: 返回前k个结果
        :return: 搜索结果列表
        """
        # 检查向量库是否存在
        if not self.vector_store:
            error_msg = "向量库不存在，请先处理文档以构建向量库"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # 获取查询的嵌入向量
        query_embeddings = self.embedding_provider.get_embeddings([query])
        query_embedding = query_embeddings[0]
        
        # 执行搜索
        results = self.vector_store.search(query_embedding, top_k=top_k)
        
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
        
        self.vector_store = VectorStore(dimension=self.dimension or 1024)
        self.vector_store.load(filepath)
        logger.info(f"向量库已从 {filepath} 成功加载")


def process_user_uploaded_documents(file_paths: List[str], rag_processor: RAGProcessor):
    """
    处理用户上传的文档
    :param file_paths: 用户上传的文档路径列表
    :param rag_processor: RAG处理器
    """
    # 导入文档处理器
    from document_processor import process_uploaded_documents
    
    # 使用文档处理器处理上传的文档
    processed_documents = process_uploaded_documents(file_paths)
    
    if not processed_documents:
        logger.warning("没有成功处理任何文档")
        return 0
    
    # 处理文档（分块、生成嵌入、存储到向量库）
    num_processed = rag_processor.process_documents(processed_documents)
    
    return num_processed