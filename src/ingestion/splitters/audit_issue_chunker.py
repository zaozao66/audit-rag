import re
import logging
from typing import List, Dict, Any
from src.ingestion.splitters.document_chunker import DocumentChunker

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AuditIssueChunker(DocumentChunker):
    """
    审计问题分块器
    专门处理审计问题整改情况表，识别表格行并将其作为独立块。
    适用于审计署发布的“中央部门单位XXXX年度预算执行等审计查出问题的整改情况”等文档。
    """
    
    def __init__(self, chunk_size: int = 1024, overlap: int = 50):
        super().__init__(chunk_size=chunk_size, overlap=overlap)
        
        # 用于识别新行的模式：多个空格或换行 + 序号 + 空格 + 部门名关键字
        self.row_split_pattern = re.compile(r'\s{2,}(\d+)\s+([\u4e00-\u9fa5]{2,}(?:部|委|局|中心|大学|学院|院|委|办))')
        
        # 审计问题特征词
        self.issue_keywords = ['整改情况', '问题摘要', '审计查出', '部门单位']

    def _create_chunk(self, document: Dict[str, Any], text: str, boundary: str) -> Dict[str, Any]:
        """辅助方法：创建分块对象"""
        return {
            'doc_id': document.get('doc_id', ''),
            'filename': document.get('filename', 'unknown'),
            'file_type': document.get('file_type', 'pdf'),
            'doc_type': 'audit_issue',
            'title': document.get('title', ''),
            'text': text.strip(),
            'semantic_boundary': boundary,
            'char_count': len(text.strip())
        }

    def chunk_audit_issues(self, document: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        处理审计问题文档，利用 DocumentProcessor 预处理生成的结构化行信息进行精准分块
        """
        text = document['text']
        filename = document.get('filename', 'unknown')
        logger.info(f"开始按审计问题结构化行分块文档: {filename}")
        
        # 识别结构化行
        if " [ROW_START] " in text:
            # 模式A：基于 DocumentProcessor 提取的表格行
            rows = [r.strip() for r in text.split(" [ROW_START] ") if r.strip()]
            chunks = []
            for row_content in rows:
                # 尝试解析列信息（针对审计整改表结构：序号 | 部门 | 问题摘要 | 整改情况）
                cells = [c.strip() for c in row_content.split('|')]
                
                # 增强语义：如果列数符合预期，添加显式标签
                if len(cells) >= 4:
                    formatted_text = f"部门单位: {cells[1]}\n问题序号: {cells[0]}\n问题摘要: {cells[2]}\n整改情况: {cells[3]}"
                    # 如果还有多余列（有些表可能有多余列），也带上
                    if len(cells) > 4:
                        formatted_text += f"\n补充信息: {' | '.join(cells[4:])}"
                else:
                    formatted_text = row_content
                
                chunks.append(self._create_chunk(document, formatted_text, "audit_issue_row"))
        else:
            # 模式B：降级方案（基于正则表达式的原始文本切分）
            parts = self.row_split_pattern.split(text)
            chunks = []
            # ... (保留原有的 row_split_pattern 处理逻辑)
            if len(parts) > 1:
                if parts[0].strip():
                    chunks.append(self._create_chunk(document, parts[0].strip(), "header"))
                for i in range(1, len(parts), 3):
                    idx = parts[i]
                    dept = parts[i+1]
                    content = parts[i+2] if i+2 < len(parts) else ""
                    row_text = f"序号: {idx}\n部门: {dept}\n内容: {content.strip()}"
                    chunks.append(self._create_chunk(document, row_text, "audit_issue_row"))
            else:
                # 最基础的行识别
                lines = text.split('\n')
                current_row = ""
                for line in lines:
                    if re.match(r'^\d+\s+', line.strip()):
                        if current_row: chunks.append(self._create_chunk(document, current_row, "audit_issue_row"))
                        current_row = line + "\n"
                    else:
                        current_row += line + "\n"
                if current_row: chunks.append(self._create_chunk(document, current_row, "audit_issue_row"))
                
        logger.info(f"审计问题分块完成，共生成 {len(chunks)} 个文本块")
        return chunks

    def chunk_documents(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        重写父类方法
        """
        all_chunks = []
        for doc in documents:
            if doc.get('doc_type') == 'audit_issue' or self._is_audit_issue(doc):
                logger.info(f"识别为审计问题文档: {doc.get('filename')}")
                chunks = self.chunk_audit_issues(doc)
            else:
                chunks = super().chunk_documents([doc])
            all_chunks.extend(chunks)
        return all_chunks

    def _is_audit_issue(self, document: Dict[str, Any]) -> bool:
        """
        判断是否为审计问题文档
        """
        filename = document.get('filename', '').lower()
        text_sample = document.get('text', '')[:1000]
        
        # 1. 检查文件名
        if '整改情况' in filename and '审计' in filename:
            return True
            
        # 2. 检查内容
        keyword_count = sum(1 for k in self.issue_keywords if k in text_sample)
        if keyword_count >= 2:
            return True
            
        # 3. 检查是否有分割模式匹配
        if self.row_split_pattern.search(text_sample):
            return True
                
        return False
