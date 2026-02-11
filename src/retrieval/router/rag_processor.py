import logging
import os
import hashlib
from datetime import datetime
from typing import List, Dict, Any, Optional
from src.indexing.vector.vector_store import VectorStore
from src.indexing.vector.embedding_providers import EmbeddingProvider
from src.indexing.metadata.document_metadata_store import DocumentMetadataStore, DocumentRecord
from src.ingestion.splitters.document_chunker import DocumentChunker
from src.ingestion.splitters.law_document_chunker import LawDocumentChunker
from src.ingestion.splitters.audit_report_chunker import AuditReportChunker
from src.ingestion.splitters.audit_issue_chunker import AuditIssueChunker
from src.ingestion.splitters.smart_chunker import SmartChunker
from src.retrieval.rerank.rerank_provider import RerankProvider
from src.llm.providers.llm_provider import LLMProvider
from src.retrieval.searchers.vector_retriever import VectorRetriever
from src.retrieval.router.intent_router import IntentRouter

logger = logging.getLogger(__name__)

class RAGProcessor:
    """RAG处理器主类 - 作为协调者组织整个RAG流程"""
    
    def __init__(self, embedding_provider: EmbeddingProvider, chunk_size: int = 512, overlap: int = 50, vector_store_path: str = "./vector_store_text_embedding", chunker_type: str = "default", rerank_provider: RerankProvider = None, llm_provider: LLMProvider = None):
        """
        初始化RAG处理器
        """
        self.embedding_provider = embedding_provider
        self.chunker_type = chunker_type
        self.vector_store_path = vector_store_path
        self.rerank_provider = rerank_provider
        self.llm_provider = llm_provider
        
        # 初始化组件
        self._init_chunker(chunker_type, chunk_size, overlap)
        self.vector_store = None
        self.dimension = None
        
        # 初始化解耦后的组件
        self.router = IntentRouter(llm_provider)
        # retriever 会在 vector_store 加载后初始化/更新
        self.retriever = None
        
        # 初始化文档元数据存储
        metadata_path = vector_store_path.replace("vector_store", "document_metadata") + ".json"
        self.metadata_store = DocumentMetadataStore(storage_path=metadata_path)
        
        logger.info(f"RAG处理器初始化完成，重排序功能{'启用' if rerank_provider else '禁用'}，LLM功能{'启用' if llm_provider else '禁用'}")

    def _init_chunker(self, chunker_type, chunk_size, overlap):
        """根据类型初始化分块器"""
        if chunker_type == "regulation":
            self.chunker = LawDocumentChunker(chunk_size=chunk_size, overlap=overlap)
        elif chunker_type == "audit_report":
            self.chunker = AuditReportChunker(chunk_size=chunk_size, overlap=overlap)
        elif chunker_type == "audit_issue":
            self.chunker = AuditIssueChunker(chunk_size=chunk_size, overlap=overlap)
        elif chunker_type == "smart":
            self.chunker = SmartChunker(chunk_size=chunk_size, overlap=overlap)
        else:
            self.chunker = DocumentChunker(chunk_size=chunk_size, overlap=overlap)
        logger.info(f"使用【{chunker_type}】分块器")

    def _ensure_vector_store(self):
        """确保向量库已加载"""
        if not self.vector_store:
            try:
                self.load_vector_store(self.vector_store_path)
            except Exception as e:
                error_msg = f"向量库不存在，请先处理文档。错误: {str(e)}"
                logger.error(error_msg)
                raise ValueError(error_msg)
        
        if not self.retriever:
            self.retriever = VectorRetriever(self.vector_store, self.embedding_provider)

    def _calculate_content_hash(self, content: str) -> str:
        """计算内容哈希"""
        return hashlib.md5(content.encode('utf-8')).hexdigest()
    
    def process_documents(self, documents: List[Dict[str, Any]], save_after_processing: bool = True) -> Dict:
        """
        处理文档入库（支持去重）
        :return: {"processed": 新增数量, "skipped": 跳过数量, "updated": 更新数量}
        """
        processed_count = 0
        skipped_count = 0
        updated_count = 0
        
        for doc in documents:
            content = doc['text']
            content_hash = self._calculate_content_hash(content)
            doc_id = content_hash[:16]
            
            # 检查是否已存在且未删除
            existing = self.metadata_store.get_document(doc_id)
            if existing and existing.status == "active":
                logger.info(f"文档已存在，跳过: {doc.get('filename', 'unknown')}")
                skipped_count += 1
                continue
            
            # 设置doc_id
            doc['doc_id'] = doc_id
            
            # 分块处理
            chunks = self.chunker.chunk_documents([doc])
            
            if not chunks:
                logger.warning(f"文档未生成分块: {doc.get('filename', 'unknown')}")
                continue
            
            # 生成嵌入向量
            texts = [c['text'] for c in chunks]
            embeddings = self.embedding_provider.get_embeddings(texts)
            
            # 确保向量库初始化
            if self.vector_store is None:
                if os.path.exists(f"{self.vector_store_path}.index"):
                    self.load_vector_store(self.vector_store_path)
                else:
                    self.dimension = len(embeddings[0]) if embeddings else 1024
                    self.vector_store = VectorStore(dimension=self.dimension)
            
            # 添加到向量库
            self.vector_store.add_embeddings(embeddings, chunks)
            
            # 记录元数据
            record = DocumentRecord(
                doc_id=doc_id,
                filename=doc.get('filename', 'unknown'),
                content_hash=content_hash,
                file_path=doc.get('file_path', ''),
                file_size=len(content.encode('utf-8')),
                doc_type=doc.get('doc_type', 'unknown'),
                upload_time=datetime.now().isoformat(),
                chunk_count=len(chunks)
            )
            
            is_new = self.metadata_store.add_document(record)
            if is_new:
                processed_count += 1
                logger.info(f"新增文档: {doc.get('filename', 'unknown')}, chunks: {len(chunks)}")
            else:
                updated_count += 1
                logger.info(f"更新文档: {doc.get('filename', 'unknown')}")
        
        # 保存向量库
        if save_after_processing and self.vector_store:
            self.save_vector_store(self.vector_store_path)
        
        # 更新检索器
        if self.vector_store:
            self.retriever = VectorRetriever(self.vector_store, self.embedding_provider)
        
        return {
            "processed": processed_count,
            "skipped": skipped_count,
            "updated": updated_count,
            "total_chunks": sum(c.chunk_count for c in self.metadata_store.list_documents())
        }

    def search(self, query: str, top_k: int = 5, use_rerank: bool = False, rerank_top_k: int = 10, doc_types: List[str] = None, titles: List[str] = None) -> List[Dict[str, Any]]:
        """基础搜索逻辑"""
        self._ensure_vector_store()
        
        # 1. 向量检索 (使用解耦后的 retriever)
        # 注意：VectorRetriever 返回的是 SearchResult 对象，为了兼容旧代码，这里转回 Dict
        initial_top_k = max(top_k * 2, rerank_top_k) if use_rerank else top_k
        results = self.retriever.search(query, top_k=initial_top_k, doc_types=doc_types, titles=titles)
        
        # 转换为旧格式 Dict 列表
        initial_results = []
        for r in results:
            initial_results.append({
                'document': r.metadata,
                'score': r.score
            })
            
        # 2. 重排序
        if use_rerank and self.rerank_provider and initial_results:
            docs = [r['document']['text'] for r in initial_results]
            reranked = self.rerank_provider.rerank(query, docs, top_k=min(len(docs), rerank_top_k))
            
            final_results = []
            for item in reranked[:top_k]:
                idx = item['index']
                if idx < len(initial_results):
                    final_results.append({
                        'score': item['relevance_score'],
                        'document': initial_results[idx]['document'],
                        'original_score': initial_results[idx]['score']
                    })
            return final_results
            
        return initial_results[:top_k]

    def search_with_intent(self, query: str, use_rerank: bool = True) -> Dict[str, Any]:
        """意图驱动搜索"""
        params = self.router.get_routed_params(query, use_rerank=use_rerank)
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
        """检索并生成回答"""
        if not self.llm_provider:
            raise ValueError("LLM功能未启用，请在初始化时传入llm_provider")
            
        params = self.router.get_routed_params(query, default_top_k=top_k, use_rerank=use_rerank, rerank_top_k=rerank_top_k)
        search_results = self.search(
            query, 
            top_k=params['top_k'], 
            use_rerank=params['use_rerank'], 
            rerank_top_k=params['rerank_top_k'],
            doc_types=params['doc_types']
        )
        
        contexts = []
        for res in search_results:
            doc = res['document']
            contexts.append({
                'text': doc['text'],
                'title': doc.get('title', ''),
                'filename': doc.get('filename', ''),
                'doc_type': doc.get('doc_type', ''),
                'score': res['score']
            })
            
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
        if not self.vector_store: return
        self.vector_store.save(filepath or self.vector_store_path)

    def load_vector_store(self, filepath: str = None):
        path = filepath or self.vector_store_path
        self.vector_store = VectorStore(dimension=self.dimension or 1024)
        self.vector_store.load(path)
        self.dimension = self.vector_store.index.d
        self.retriever = VectorRetriever(self.vector_store, self.embedding_provider)

    def clear_vector_store(self):
        if self.vector_store:
            self.vector_store = VectorStore(dimension=self.dimension or 1024)
            self.retriever = VectorRetriever(self.vector_store, self.embedding_provider)

    def process_documents_from_files(self, file_paths: List[str], save_after_processing: bool = True, doc_type: str = 'internal_regulation', title: str = None, original_filenames: List[str] = None) -> Dict:
        """从文件处理文档"""
        from src.ingestion.parsers.document_processor import process_uploaded_documents
        processed_documents = process_uploaded_documents(file_paths, doc_type=doc_type, title=title, original_filenames=original_filenames)
        if not processed_documents:
            return {"processed": 0, "skipped": 0, "updated": 0, "total_chunks": 0}
        return self.process_documents(processed_documents, save_after_processing=save_after_processing)
    
    # ========== 文档管理接口 ==========
    
    def list_documents(self, doc_type: str = None, keyword: str = None, include_deleted: bool = False) -> List[Dict]:
        """列出已上传文档"""
        status = None if include_deleted else "active"
        records = self.metadata_store.list_documents(doc_type=doc_type, status=status, keyword=keyword)
        return [r.to_dict() for r in records]
    
    def get_document_detail(self, doc_id: str) -> Optional[Dict]:
        """获取文档详情"""
        record = self.metadata_store.get_document(doc_id)
        if not record:
            return None
        
        detail = record.to_dict()
        
        # 获取该文档的所有chunks
        if self.vector_store:
            chunks = self.vector_store.get_document_chunks(doc_id)
            detail['chunks'] = chunks
        
        return detail
    
    def get_document_chunks(self, doc_id: str, include_text: bool = True) -> Dict:
        """获取文档的分块详情"""
        record = self.metadata_store.get_document(doc_id)
        if not record:
            return {"error": "文档不存在"}
        
        if not self.vector_store:
            return {"error": "向量库未加载"}
        
        chunks = self.vector_store.get_document_chunks(doc_id)
        
        # 统计信息
        total_chars = sum(c['char_count'] for c in chunks)
        avg_chunk_size = total_chars // len(chunks) if chunks else 0
        
        if not include_text:
            chunks = [{k: v for k, v in c.items() if k != 'text'} for c in chunks]
        
        return {
            "doc_id": doc_id,
            "filename": record.filename,
            "doc_type": record.doc_type,
            "upload_time": record.upload_time,
            "chunk_count": len(chunks),
            "total_chars": total_chars,
            "avg_chunk_size": avg_chunk_size,
            "chunks": chunks
        }
    
    def delete_document(self, doc_id: str) -> Dict:
        """删除指定文档"""
        # 1. 从元数据存储标记删除
        if not self.metadata_store.delete_document(doc_id):
            return {"success": False, "error": "文档不存在"}
        
        # 2. 从向量库删除
        removed_chunks = 0
        if self.vector_store:
            removed_chunks = self.vector_store.remove_document_chunks(doc_id)
        
        # 3. 保存更新后的向量库
        if self.vector_store:
            self.save_vector_store(self.vector_store_path)
        
        return {
            "success": True,
            "doc_id": doc_id,
            "removed_chunks": removed_chunks
        }
    
    def get_document_stats(self) -> Dict:
        """获取文档统计信息"""
        return self.metadata_store.get_stats()

def process_user_uploaded_documents(file_paths: List[str], rag_processor: RAGProcessor):
    from src.ingestion.parsers.document_processor import process_uploaded_documents
    processed_documents = process_uploaded_documents(file_paths)
    if not processed_documents: return 0
    return rag_processor.process_documents(processed_documents)
