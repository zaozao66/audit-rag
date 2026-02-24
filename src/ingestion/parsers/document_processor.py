import os
import logging
from typing import Dict, Any, List
from docx import Document
import pdfplumber
import chardet


# 定义文档类型枚举
DOCUMENT_TYPES = {
    'internal_regulation': '内部制度',
    'external_regulation': '外部制度',
    'internal_report': '内部报告',
    'external_report': '外部报告',
    'audit_issue': '审计问题'
}

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class DocumentProcessor:
    """
    文档处理器 - 支持多种文档格式（PDF、DOCX、TXT）
    """
    
    @staticmethod
    def detect_file_type(file_path: str) -> str:
        """
        检测文件类型
        :param file_path: 文件路径
        :return: 文件类型 ('pdf', 'docx', 'txt', 'unknown')
        """
        _, ext = os.path.splitext(file_path.lower())
        return ext.lstrip('.')
    
    @staticmethod
    def load_document(file_path: str, doc_type: str = 'default') -> str:
        """
        根据文件类型加载文档内容
        :param file_path: 文件路径
        :param doc_type: 文档类型，审计问题类型会特殊处理表格
        :return: 文档文本内容
        """
        file_type = DocumentProcessor.detect_file_type(file_path)
        logger.info(f"检测到文件类型: {file_type}，文件路径: {file_path}")
        
        if file_type == 'pdf':
            return DocumentProcessor._load_pdf(file_path, is_audit_issue=(doc_type == 'audit_issue'))
        elif file_type == 'docx':
            return DocumentProcessor._load_docx(file_path)
        elif file_type == 'txt':
            return DocumentProcessor._load_txt(file_path)
        else:
            raise ValueError(f"不支持的文件类型: {file_type}")
    
    @staticmethod
    def _load_pdf(file_path: str, is_audit_issue: bool = False) -> str:
        """
        加载PDF文档
        :param file_path: PDF文件路径
        :param is_audit_issue: 是否为审计问题类型（执行表格提取）
        :return: 文档文本内容
        """
        logger.info(f"开始加载PDF文档: {file_path} (审计问题模式: {is_audit_issue})")
        text_parts = []
        
        try:
            with pdfplumber.open(file_path) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    page_tag = f"[[PAGE:{page_num + 1}]]"
                    if is_audit_issue:
                        # 审计问题模式：尝试提取表格
                        tables = page.extract_tables()
                        if tables:
                            for table in tables:
                                # 处理表格行，保持语义配对并继承上下文
                                current_idx = ""
                                current_dept = ""
                                                        
                                for row in table:
                                    if not row or all(not cell for cell in row):
                                        continue
                                                            
                                    # 过滤掉表头行
                                    row_content_str = "".join([str(c) for c in row if c])
                                    if any(k in row_content_str for k in ['序号', '问题摘要', '整改情况']):
                                        continue
                                                            
                                    # 提取并清理单元格
                                    cells = [str(cell).replace('\n', ' ').strip() if cell else "" for cell in row]
                                                            
                                    if len(cells) >= 4:
                                        idx, dept, issue, rectify = cells[0], cells[1], cells[2], cells[3]
                                                                
                                        # 更新并继承上下文（序号和部门）
                                        if idx: current_idx = idx
                                        if dept: current_dept = dept
                                                                
                                        # 只有当问题摘要或整改情况不为空时才生成记录
                                        if issue or rectify:
                                            # 将每一行作为一个独立的 [ROW_START] 标记
                                            row_text = f" [ROW_START] {page_tag} {current_idx} | {current_dept} | {issue} | {rectify}"
                                            # 如果还有多余列（补充信息），也带上
                                            if len(cells) > 4:
                                                row_text += " | " + " | ".join(cells[4:])
                                            text_parts.append(row_text)
                        else:
                            # 如果没提取到表格，降级使用文本提取
                            page_text = page.extract_text()
                            if page_text:
                                text_parts.append(f"{page_tag}\n{page_text}")
                    else:
                        # 普通模式：直接提取文本
                        page_text = page.extract_text()
                        if page_text:
                            text_parts.append(f"{page_tag}\n{page_text}")
                    logger.debug(f"处理PDF第 {page_num + 1} 页")
            
            full_text = "\n".join(text_parts)
            logger.info(f"PDF文档加载完成，总内容长度: {len(full_text)}")
            return full_text
            
        except Exception as e:
            logger.error(f"加载PDF文档失败: {e}")
            raise
    
    @staticmethod
    def _load_docx(file_path: str) -> str:
        """
        加载DOCX文档
        :param file_path: DOCX文件路径
        :return: 文档文本内容
        """
        logger.info(f"开始加载DOCX文档: {file_path}")
        
        try:
            doc = Document(file_path)
            paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]
            full_text = "\n".join(paragraphs)
            
            logger.info(f"DOCX文档加载完成，总文本长度: {len(full_text)}")
            return full_text
            
        except Exception as e:
            logger.error(f"加载DOCX文档失败: {e}")
            raise
    
    @staticmethod
    def _load_txt(file_path: str) -> str:
        """
        加载TXT文档
        :param file_path: TXT文件路径
        :return: 文档文本内容
        """
        logger.info(f"开始加载TXT文档: {file_path}")
        
        # 检测文件编码
        with open(file_path, 'rb') as f:
            raw_data = f.read()
            encoding_result = chardet.detect(raw_data)
            encoding = encoding_result['encoding']
        
        logger.info(f"检测到文件编码: {encoding}")
        
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                content = f.read()
            
            logger.info(f"TXT文档加载完成，总文本长度: {len(content)}")
            return content
            
        except Exception as e:
            logger.error(f"加载TXT文档失败: {e}")
            raise


def process_uploaded_documents(file_paths: List[str], doc_type: str = 'internal_regulation', title: str = None, original_filenames: List[str] = None) -> List[Dict[str, Any]]:
    """
    处理用户上传的多个文档
    :param file_paths: 文件路径列表
    :param doc_type: 文档类型 (internal_regulation, external_regulation, internal_report, external_report)
    :param title: 文档标题
    :param original_filenames: 原始文件名列表（可选）
    :return: 文档列表，每个元素包含文档内容和元数据
    """
    logger.info(f"开始处理 {len(file_paths)} 个上传的文档，类型: {doc_type}")
    
    documents = []
    
    for idx, file_path in enumerate(file_paths):
        logger.info(f"正在处理文档 {idx + 1}/{len(file_paths)}: {file_path}")
        
        try:
            # 获取文件名：优先使用传入的原始文件名，否则从路径提取
            if original_filenames and idx < len(original_filenames):
                filename = original_filenames[idx]
            else:
                filename = os.path.basename(file_path)
            
            # 加载文档内容
            content = DocumentProcessor.load_document(file_path, doc_type=doc_type)
            
            # 创建文档对象
            doc_obj = {
                'doc_id': f'doc_{idx}',
                'filename': filename,
                'file_path': file_path,
                'file_type': DocumentProcessor.detect_file_type(filename), # 使用文件名检测类型更准确
                'doc_type': doc_type,
                'title': title or filename,
                'text': content,
                'char_count': len(content)
            }
            
            documents.append(doc_obj)
            logger.info(f"文档 {filename} 处理完成，字符数: {len(content)}, 类型: {doc_type}")
            
        except Exception as e:
            logger.error(f"处理文档 {file_path} 时发生错误: {e}")
            continue  # 继续处理其他文档
    
    logger.info(f"所有文档处理完成，成功处理 {len(documents)} 个文档")
    return documents

