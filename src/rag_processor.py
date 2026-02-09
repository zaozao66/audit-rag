import logging
from typing import List, Dict, Any, Optional
from vector_store import VectorStore
from document_chunker import DocumentChunker
from law_document_chunker import LawDocumentChunker
from audit_report_chunker import AuditReportChunker
from audit_issue_chunker import AuditIssueChunker
from embedding_providers import EmbeddingProvider
from rerank_provider import RerankProvider
from llm_provider import LLMProvider

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class SmartChunker:
    """
    智能分块器 - 根据文档类型自动选择合适的分块策略
    """
    
    def __init__(self, chunk_size: int = 512, overlap: int = 50):
        """
        初始化智能分块器
        :param chunk_size: 每个块的最大字符数
        :param overlap: 相邻块之间的重叠字符数
        """
        self.chunk_size = chunk_size
        self.overlap = overlap
        
        # 初始化各种分块器
        self.law_chunker = LawDocumentChunker(chunk_size=chunk_size, overlap=overlap)
        self.audit_chunker = AuditReportChunker(chunk_size=chunk_size, overlap=overlap)
        self.issue_chunker = AuditIssueChunker(chunk_size=chunk_size, overlap=overlap)
        self.default_chunker = DocumentChunker(chunk_size=chunk_size, overlap=overlap)
        
        logger.info(f"智能分块器初始化完成，块大小: {chunk_size}, 重叠: {overlap}")
    
    def chunk_documents(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        智能分块文档 - 根据文档类型自动选择合适的分块器
        :param documents: 文档列表
        :return: 分块后的文档列表
        """
        all_chunks = []
        
        for doc in documents:
            doc_type = doc.get('doc_type', '')
            filename = doc.get('filename', '')
            
            # 根据文档类型选择分块器
            if doc_type == 'audit_issue' or self.issue_chunker._is_audit_issue(doc):
                # 使用审计问题分块器
                logger.info(f"文档 {filename} 使用审计问题分块器")
                chunks = self.issue_chunker.chunk_audit_issues(doc)
            elif doc_type in ['internal_report', 'external_report'] or self.audit_chunker._is_audit_report(doc):
                # 使用审计报告分块器
                logger.info(f"文档 {filename} 使用审计报告分块器")
                chunks = self.audit_chunker.chunk_audit_report(doc)
            elif doc_type in ['internal_regulation', 'external_regulation'] or self.law_chunker._is_law_document(doc):
                # 使用法规文档分块器
                logger.info(f"文档 {filename} 使用法规文档分块器")
                chunks = self.law_chunker.chunk_law_document(doc)
            else:
                # 使用默认分块器
                logger.info(f"文档 {filename} 使用默认分块器")
                chunks = self.default_chunker.chunk_documents([doc])
            
            all_chunks.extend(chunks)
        
        return all_chunks



class RAGProcessor:
    """RAG处理器主类 - 协调整个RAG流程"""
    
    def __init__(self, embedding_provider: EmbeddingProvider, chunk_size: int = 512, overlap: int = 50, vector_store_path: str = "./vector_store_text_embedding", chunker_type: str = "default", rerank_provider: RerankProvider = None, llm_provider: LLMProvider = None):
        """
        初始化RAG处理器
        :param embedding_provider: 嵌入提供者
        :param chunk_size: 文本块大小
        :param overlap: 块间重叠大小
        :param vector_store_path: 向量库存储路径
        :param chunker_type: 分块器类型 ("default", "regulation", "audit_report", "smart")
        :param rerank_provider: 重排序提供者
        :param llm_provider: LLM提供者
        """
        self.embedding_provider = embedding_provider
        self.chunker_type = chunker_type
        
        # 根据类型选择分块器
        if chunker_type == "regulation":
            self.chunker = LawDocumentChunker(chunk_size=chunk_size, overlap=overlap)
            logger.info("使用【制度文件】专门分块器")
        elif chunker_type == "audit_report":
            self.chunker = AuditReportChunker(chunk_size=chunk_size, overlap=overlap)
            logger.info("使用【审计报告】专门分块器")
        elif chunker_type == "audit_issue":
            self.chunker = AuditIssueChunker(chunk_size=chunk_size, overlap=overlap)
            logger.info("使用【审计问题】专门分块器")
        elif chunker_type == "smart":
            self.chunker = SmartChunker(chunk_size=chunk_size, overlap=overlap)
            logger.info("使用【智能识别】分块器")
        else:
            self.chunker = DocumentChunker(chunk_size=chunk_size, overlap=overlap)
            logger.info("使用【默认】普通分块器")
            
        self.rerank_provider = rerank_provider
        self.llm_provider = llm_provider
        self.vector_store = None
        self.dimension = None  # 将在第一次调用时确定
        self.vector_store_path = vector_store_path
        logger.info(f"RAG处理器初始化完成，重排序功能{'启用' if rerank_provider else '禁用'}，LLM功能{'启用' if llm_provider else '禁用'}")
    
    def process_documents(self, documents: List[Dict[str, Any]], save_after_processing: bool = True):
        """
        处理文档：分块、生成嵌入向量、存储到向量库
        :param documents: 文档列表
        :param save_after_processing: 是否在处理后自动保存向量库
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
        
        # 强制显示所有分块内容（根据用户偏好）
        logger.info("所有文本块内容:")
        # for i, chunk in enumerate(chunks):
            # logger.info(f"  块 {i+1} ({chunk.get('semantic_boundary', 'unknown')}): {chunk['text']}")
        
        # 步骤2: 提取文本用于嵌入
        texts_for_embedding = [chunk['text'] for chunk in chunks]
        
        # 步骤3: 获取嵌入向量
        logger.info(f"开始调用嵌入模型处理 {len(texts_for_embedding)} 个文本块")
        embeddings = self.embedding_provider.get_embeddings(texts_for_embedding)
        logger.info(f"嵌入模型处理完成，获得 {len(embeddings)} 个向量")
        
        # 确定嵌入维度
        if self.dimension is None:
            self.dimension = len(embeddings[0]) if embeddings else 1024
        
        # 步骤4: 如果向量库不存在则尝试加载，否则创建新库
        if self.vector_store is None:
            import os
            # 检查索引文件和文档文件是否都存在
            index_path = f"{self.vector_store_path}.index"
            docs_path = f"{self.vector_store_path}.docs"
            
            if os.path.exists(index_path) and os.path.exists(docs_path):
                try:
                    logger.info(f"检测到现有向量库，尝试加载: {self.vector_store_path}")
                    self.load_vector_store(self.vector_store_path)
                    logger.info(f"向量库加载成功，当前包含 {self.vector_store.index.ntotal} 个向量")
                except Exception as e:
                    logger.warning(f"加载现有向量库失败 ({e})，将创建新的向量库")
                    self.vector_store = VectorStore(dimension=self.dimension)
            else:
                logger.info("未检测到现有向量库，创建新的向量库...")
                self.vector_store = VectorStore(dimension=self.dimension)
        else:
            logger.info(f"向量库已在内存中，将追加新文档（当前包含 {self.vector_store.index.ntotal} 个向量）...")
        
        # 步骤5: 添加到向量库
        self.vector_store.add_embeddings(embeddings, chunks)
        
        # 如果需要，在处理后保存向量库
        if save_after_processing:
            self.save_vector_store(self.vector_store_path)
        
        return len(chunks)
    
    def search(self, query: str, top_k: int = 5, use_rerank: bool = False, rerank_top_k: int = 10, doc_types: List[str] = None, titles: List[str] = None) -> List[Dict[str, Any]]:
        """
        搜索相关文档
        :param query: 查询文本
        :param top_k: 返回前k个结果
        :param use_rerank: 是否使用重排序
        :param rerank_top_k: 重排序时考虑的文档数量
        :param doc_types: 文档类型过滤列表 (可选)
        :param titles: 标题过滤列表 (可选)
        :return: 搜索结果列表
        """
        # 检查向量库是否存在
        if not self.vector_store:
            # 尝试从默认路径加载向量库
            try:
                self.load_vector_store(self.vector_store_path)
            except Exception as e:
                error_msg = f"向量库不存在，请先处理文档以构建向量库。尝试加载向量库时出错: {str(e)}"
                logger.error(error_msg)
                raise ValueError(error_msg)
        
        # 获取查询的嵌入向量
        logger.info(f"开始调用嵌入模型处理查询: {query}")
        query_embeddings = self.embedding_provider.get_embeddings([query])
        query_embedding = query_embeddings[0]
        logger.info(f"查询嵌入模型处理完成，获得向量维度: {len(query_embedding)}")
        
        # 执行初步搜索
        initial_top_k = max(top_k * 2, rerank_top_k) if use_rerank else top_k
        initial_results = self.vector_store.search(query_embedding, top_k=initial_top_k, doc_types=doc_types, titles=titles)
        
        # 如果需要重排序且有重排序提供者
        if use_rerank and self.rerank_provider:
            logger.info(f"执行重排序，初始结果数: {len(initial_results)}, 重排前取: {rerank_top_k}, 最终返回: {top_k}")
            
            # 提取文档文本
            documents = [result['document']['text'] for result in initial_results]
            
            # 执行重排序
            reranked_results = self.rerank_provider.rerank(query, documents, top_k=min(len(documents), rerank_top_k))
            
            # 将重排序结果与原始结果合并
            final_results = []
            for rerank_item in reranked_results[:top_k]:
                original_index = rerank_item['index']
                if original_index < len(initial_results):
                    original_result = initial_results[original_index]
                    # 更新分数为重排序分数
                    updated_result = {
                        'score': rerank_item['relevance_score'],
                        'document': original_result['document'],
                        'original_score': original_result['score']  # 保留原始相似度分数
                    }
                    final_results.append(updated_result)
        else:
            # 不使用重排序，直接返回初步搜索结果
            final_results = initial_results[:top_k]
        
        # 强制显示所有搜索结果的完整文本（根据用户偏好）
        logger.info(f"查询: {query}")
        logger.info("搜索结果:")
        for i, result in enumerate(final_results, 1):
            original_score = result.get('original_score', result['score'])
            if 'original_score' in result:
                logger.info(f"{i}. 重排序分数: {result['score']:.4f} (原始分数: {original_score:.4f})")
            else:
                logger.info(f"{i}. 相似度分数: {result['score']:.4f}")
            doc = result['document']
            logger.info(f"   类型: {doc.get('doc_type', 'unknown')}, 标题: {doc.get('title', 'unknown')}")
            logger.info(f"   文本: {doc['text'][:200]}...")  # 只显示前200个字符
        
        return final_results
    
    def _get_routed_params(self, query: str, default_top_k: int = 5, use_rerank: bool = True, rerank_top_k: int = 10) -> Dict[str, Any]:
        """
        统一意图识别和参数路由逻辑
        """
        intent_info = {"intent": "comprehensive_query", "suggested_top_k": default_top_k, "reason": "默认路由"}
        if self.llm_provider:
            intent_info = self.llm_provider.detect_intent(query)
        
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

    def search_with_intent(self, query: str, use_rerank: bool = True) -> Dict[str, Any]:
        """
        带意图识别的智能检索（完全由意图路由决定参数）
        :param query: 查询文本
        :param use_rerank: 是否允许使用重排序
        :return: 包含意图信息和搜索结果的字典
        """
        # 获取路由参数
        params = self._get_routed_params(query, use_rerank=use_rerank)
        
        # 执行检索
        logger.info(f"执行意图驱动搜索: intent={params['intent']}, top_k={params['top_k']}")
        search_results = self.search(
            query, 
            top_k=params['top_k'], 
            use_rerank=params['use_rerank'], 
            rerank_top_k=params['rerank_top_k'],
            doc_types=params['doc_types']
        )
        
        return {
            "query": query,
            "intent": params['intent'],
            "intent_reason": params['reason'],
            "suggested_top_k": params['top_k'],
            "search_results": search_results
        }

    def search_with_llm_answer(self, query: str, top_k: int = 5, use_rerank: bool = True, rerank_top_k: int = 10) -> Dict[str, Any]:
        """
        检索并使用LLM生成回答（支持智能路由）
        """
        if not self.llm_provider:
            raise ValueError("LLM功能未启用，请在初始化时传入llm_provider")
        
        # 获取路由参数
        params = self._get_routed_params(query, default_top_k=top_k, use_rerank=use_rerank, rerank_top_k=rerank_top_k)
        
        # 执行检索
        logger.info(f"执行带路由检索回答: intent={params['intent']}, top_k={params['top_k']}")
        search_results = self.search(
            query, 
            top_k=params['top_k'], 
            use_rerank=params['use_rerank'], 
            rerank_top_k=params['rerank_top_k'],
            doc_types=params['doc_types']
        )
        
        # 准备上下文
        contexts = []
        for result in search_results:
            doc = result['document']
            contexts.append({
                'text': doc['text'],
                'title': doc.get('title', ''),
                'filename': doc.get('filename', ''),
                'doc_type': doc.get('doc_type', ''),
                'score': result['score']
            })
        
        # 调用LLM回答
        llm_result = self.llm_provider.generate_answer(query, contexts)
        
        return {
            'query': query,
            'intent': params['intent'],
            'intent_reason': params['reason'],
            'answer': llm_result['answer'],
            'contexts': contexts,
            'contexts_used': len(contexts),
            'search_results': search_results,
            'llm_usage': llm_result.get('usage', {}),
            'model': llm_result.get('model', '')
        }
    
    def save_vector_store(self, filepath: str = None):
        """保存向量库"""
        if filepath is None:
            filepath = self.vector_store_path
        
        logger.info(f"开始保存向量库到 {filepath}")
        
        if not self.vector_store:
            error_msg = "没有可保存的向量库"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        self.vector_store.save(filepath)
        logger.info(f"向量库已成功保存到 {filepath}")
    
    def load_vector_store(self, filepath: str = None):
        """加载向量库"""
        if filepath is None:
            filepath = self.vector_store_path
            
        logger.info(f"开始从 {filepath} 加载向量库")
        
        # 确定维度，优先使用已知维度
        dimension_to_use = self.dimension or 1024
        
        self.vector_store = VectorStore(dimension=dimension_to_use)
        self.vector_store.load(filepath)
        self.dimension = self.vector_store.index.d  # 同步加载后的维度
        logger.info(f"向量库已从 {filepath} 成功加载，包含 {self.vector_store.index.ntotal} 个向量，维度: {self.dimension}")
    
    def clear_vector_store(self):
        """清空向量库"""
        if self.vector_store:
            self.vector_store = VectorStore(dimension=self.dimension or 1024)
            logger.info("向量库已清空")
        else:
            logger.info("向量库未初始化，无需清空")
    
    def process_documents_from_files(self, file_paths: List[str], save_after_processing: bool = True, doc_type: str = 'internal_regulation', title: str = None, original_filenames: List[str] = None):
        """
        从文件路径处理文档：读取文件、分块、生成嵌入向量、存储到向量库
        :param file_paths: 文件路径列表
        :param save_after_processing: 是否在处理后自动保存向量库
        :param doc_type: 文档类型 (internal_regulation, external_regulation, internal_report, external_report)
        :param title: 文档标题
        :param original_filenames: 原始文件名列表（可选）
        :return: 生成的文本块数量
        """
        # 导入文档处理器
        from document_processor import process_uploaded_documents
        
        # 使用文档处理器处理上传的文档
        processed_documents = process_uploaded_documents(file_paths, doc_type=doc_type, title=title, original_filenames=original_filenames)
        
        if not processed_documents:
            logger.warning("没有成功处理任何文档")
            return 0
        
        # 处理文档（分块、生成嵌入、存储到向量库）
        num_processed = self.process_documents(processed_documents, save_after_processing=save_after_processing)
        
        return num_processed


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