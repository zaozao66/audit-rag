import logging
from typing import List, Dict, Any
from src.ingestion.splitters.document_chunker import DocumentChunker
from src.ingestion.splitters.law_document_chunker import LawDocumentChunker
from src.ingestion.splitters.technical_standard_chunker import TechnicalStandardChunker
from src.ingestion.splitters.speech_material_chunker import SpeechMaterialChunker
from src.ingestion.splitters.case_material_chunker import CaseMaterialChunker
from src.ingestion.splitters.audit_report_chunker import AuditReportChunker
from src.ingestion.splitters.audit_issue_chunker import AuditIssueChunker

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
        self.technical_chunker = TechnicalStandardChunker(chunk_size=chunk_size, overlap=overlap)
        self.speech_chunker = SpeechMaterialChunker(chunk_size=chunk_size, overlap=overlap)
        self.case_chunker = CaseMaterialChunker(chunk_size=chunk_size, overlap=overlap)
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

            is_regulation_doc_type = doc_type in ['internal_regulation', 'external_regulation']
            is_technical_standard = self.technical_chunker._is_technical_standard(doc)
            is_speech_material = self.speech_chunker._is_speech_material(doc)
            is_case_material = self.case_chunker._is_case_material(doc)

            # 根据文档类型选择分块器
            if doc_type == 'audit_issue' or self.issue_chunker._is_audit_issue(doc):
                logger.info(f"文档 {filename} 使用审计问题分块器")
                chunks = self.issue_chunker.chunk_audit_issues(doc)
            elif is_case_material:
                logger.info(f"文档 {filename} 使用典型案例分块器")
                chunks = self.case_chunker.chunk_case_material(doc)
            elif is_speech_material:
                logger.info(f"文档 {filename} 使用讲话材料分块器")
                chunks = self.speech_chunker.chunk_speech_material(doc)
            elif is_regulation_doc_type:
                if is_technical_standard:
                    logger.info(f"文档 {filename} 使用技术规范分块器")
                    chunks = self.technical_chunker.chunk_technical_standard(doc)
                else:
                    logger.info(f"文档 {filename} 使用法规文档分块器")
                    chunks = self.law_chunker.chunk_law_document(doc)
            elif doc_type in ['internal_report', 'external_report'] or self.audit_chunker._is_audit_report(doc):
                logger.info(f"文档 {filename} 使用审计报告分块器")
                chunks = self.audit_chunker.chunk_audit_report(doc)
            elif self.law_chunker._is_law_document(doc):
                if is_technical_standard:
                    logger.info(f"文档 {filename} 使用技术规范分块器")
                    chunks = self.technical_chunker.chunk_technical_standard(doc)
                else:
                    logger.info(f"文档 {filename} 使用法规文档分块器")
                    chunks = self.law_chunker.chunk_law_document(doc)
            else:
                logger.info(f"文档 {filename} 使用默认分块器")
                chunks = self.default_chunker.chunk_documents([doc])
            
            all_chunks.extend(chunks)
        
        return all_chunks
