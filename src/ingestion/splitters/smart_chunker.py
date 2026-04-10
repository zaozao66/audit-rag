import logging
import re
from typing import List, Dict, Any
from src.ingestion.splitters.document_chunker import DocumentChunker
from src.ingestion.splitters.law_document_chunker import LawDocumentChunker
from src.ingestion.splitters.technical_standard_chunker import TechnicalStandardChunker
from src.ingestion.splitters.speech_material_chunker import SpeechMaterialChunker
from src.ingestion.splitters.case_material_chunker import CaseMaterialChunker
from src.ingestion.splitters.audit_report_chunker import AuditReportChunker
from src.ingestion.splitters.audit_issue_chunker import AuditIssueChunker

logger = logging.getLogger(__name__)

TECHNICAL_FILENAME_HINTS = [
    "信息安全",
    "信息系统",
    "电子信息系统",
    "网络安全",
    "数据安全",
    "系统审计",
    "技术",
    "机房",
    "运行维护",
]
TECHNICAL_TITLE_HINTS = ["规范", "标准", "技术规范", "技术标准", "指南"]
ENTERPRISE_ACCOUNTING_PROFILE = "enterprise_accounting_standards_compendium"

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

    @staticmethod
    def _label_values(document: Dict[str, Any]) -> List[str]:
        labels = document.get('knowledge_labels') or {}
        if not isinstance(labels, dict):
            return []
        values: List[str] = []
        for raw_values in labels.values():
            items = raw_values if isinstance(raw_values, list) else [raw_values]
            values.extend(str(item or '').strip() for item in items if str(item or '').strip())
        return values

    @staticmethod
    def _has_technical_route_hint(document: Dict[str, Any]) -> bool:
        filename = str(document.get('filename', '') or '')
        title = str(document.get('title', '') or '')
        text = str(document.get('text', '') or '')
        name_sample = f"{filename}\n{title}"
        compact_name = re.sub(r"\s+", "", name_sample)
        text_sample = text[:8000]

        has_technical_name = any(token in compact_name for token in TECHNICAL_FILENAME_HINTS)
        has_standard_name = any(token in compact_name for token in TECHNICAL_TITLE_HINTS)
        if has_technical_name and has_standard_name:
            return True

        technical_structure_count = sum(
            1
            for pattern in [
                r"(?:^|\n)\d+\.\d+(?:\.\d+)?\s+[^\n]{1,80}",
                r"(?:^|\n)[A-Z]\.\d+(?:\.\d+)?\s+[^\n]{1,80}",
                r"(?:^|\n)[A-Z]{1,3}\d+(?:\.\d+)+\s+[^\n]{1,120}",
                r"附\s*录\s*[A-ZＡ-Ｚ]",
            ]
            if re.search(pattern, text_sample)
        )
        return has_technical_name and technical_structure_count >= 2

    def _resolve_route(
        self,
        doc: Dict[str, Any],
        is_technical_standard: bool,
        is_speech_material: bool,
        is_case_material: bool,
    ) -> Dict[str, str]:
        doc_type = str(doc.get('doc_type', '') or '')
        ingest_profile = str(doc.get('ingest_profile', '') or '').strip()
        label_values = self._label_values(doc)

        if doc_type == 'audit_issue' or self.issue_chunker._is_audit_issue(doc):
            return {'chunker_type': 'audit_issue', 'reason': 'doc_type_or_audit_issue_feature'}
        if 'case_library' in label_values:
            return {'chunker_type': 'case_material', 'reason': 'knowledge_label_case_library'}
        if is_case_material:
            return {'chunker_type': 'case_material', 'reason': 'case_material_feature'}
        if 'important_speeches' in label_values:
            return {'chunker_type': 'speech_material', 'reason': 'knowledge_label_important_speeches'}
        if is_speech_material:
            return {'chunker_type': 'speech_material', 'reason': 'speech_material_feature'}

        if ingest_profile == ENTERPRISE_ACCOUNTING_PROFILE:
            return {'chunker_type': 'regulation', 'reason': 'enterprise_accounting_profile'}

        is_regulation_doc_type = doc_type in ['internal_regulation', 'external_regulation']
        if is_technical_standard:
            return {'chunker_type': 'technical_standard', 'reason': 'technical_standard_feature'}
        if is_regulation_doc_type and self._has_technical_route_hint(doc):
            return {'chunker_type': 'technical_standard', 'reason': 'technical_filename_or_structure_hint'}
        if is_regulation_doc_type:
            return {'chunker_type': 'regulation', 'reason': 'regulation_doc_type'}
        if doc_type in ['internal_report', 'external_report'] or self.audit_chunker._is_audit_report(doc):
            return {'chunker_type': 'audit_report', 'reason': 'doc_type_or_audit_report_feature'}
        if self.law_chunker._is_law_document(doc):
            if self._has_technical_route_hint(doc):
                return {'chunker_type': 'technical_standard', 'reason': 'technical_filename_or_structure_hint'}
            return {'chunker_type': 'regulation', 'reason': 'law_document_feature'}
        return {'chunker_type': 'default', 'reason': 'fallback_default'}

    def _chunk_by_route(self, doc: Dict[str, Any], route: str) -> List[Dict[str, Any]]:
        if route == 'audit_issue':
            return self.issue_chunker.chunk_audit_issues(doc)
        if route == 'case_material':
            return self.case_chunker.chunk_case_material(doc)
        if route == 'speech_material':
            return self.speech_chunker.chunk_speech_material(doc)
        if route == 'technical_standard':
            return self.technical_chunker.chunk_technical_standard(doc)
        if route == 'regulation':
            return self.law_chunker.chunk_law_document(doc)
        if route == 'audit_report':
            return self.audit_chunker.chunk_audit_report(doc)
        return self.default_chunker.chunk_documents([doc])
    
    def chunk_documents(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        智能分块文档 - 根据文档类型自动选择合适的分块器
        :param documents: 文档列表
        :return: 分块后的文档列表
        """
        all_chunks = []
        
        for doc in documents:
            filename = doc.get('filename', '')

            is_technical_standard = self.technical_chunker._is_technical_standard(doc)
            is_speech_material = self.speech_chunker._is_speech_material(doc)
            is_case_material = self.case_chunker._is_case_material(doc)
            route = self._resolve_route(
                doc,
                is_technical_standard=is_technical_standard,
                is_speech_material=is_speech_material,
                is_case_material=is_case_material,
            )
            resolved_chunker_type = route['chunker_type']
            route_reason = route['reason']

            logger.info("文档 %s 使用 %s 分块器，路由原因: %s", filename, resolved_chunker_type, route_reason)
            chunks = self._chunk_by_route(doc, resolved_chunker_type)

            for chunk in chunks:
                chunk.setdefault('requested_chunker_type', 'smart')
                chunk.setdefault('resolved_chunker_type', resolved_chunker_type)
                chunk.setdefault('chunker_route_reason', route_reason)
            
            all_chunks.extend(chunks)
        
        return all_chunks
