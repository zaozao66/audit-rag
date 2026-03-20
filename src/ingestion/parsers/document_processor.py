import os
import logging
import re
from typing import Dict, Any, List, Optional, Set
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
                # 普通模式下先收集每页文本，统一做“重复页眉页脚/页码”清洗
                normal_mode_pages: List[List[str]] = []

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
                            lines = DocumentProcessor._normalize_pdf_lines(page_text.splitlines())
                            normal_mode_pages.append(lines)
                        else:
                            normal_mode_pages.append([])
                    logger.debug(f"处理PDF第 {page_num + 1} 页")

                if not is_audit_issue:
                    repeated_header_footer = DocumentProcessor._detect_repeated_header_footer_lines(normal_mode_pages)
                    for page_num, lines in enumerate(normal_mode_pages):
                        page_tag = f"[[PAGE:{page_num + 1}]]"
                        cleaned_lines = DocumentProcessor._clean_pdf_page_lines(lines, repeated_header_footer)
                        if cleaned_lines:
                            text_parts.append(f"{page_tag}\n" + "\n".join(cleaned_lines))
                        else:
                            text_parts.append(page_tag)
            
            full_text = "\n".join(text_parts)
            logger.info(f"PDF文档加载完成，总内容长度: {len(full_text)}")
            return full_text
            
        except Exception as e:
            logger.error(f"加载PDF文档失败: {e}")
            raise

    @staticmethod
    def _normalize_pdf_lines(lines: List[str]) -> List[str]:
        normalized: List[str] = []
        for line in lines:
            cleaned = re.sub(r"\s+", " ", str(line or "")).strip()
            if cleaned:
                normalized.append(cleaned)
        return normalized

    @staticmethod
    def _looks_like_page_number_line(line: str) -> bool:
        value = str(line or "").strip()
        if not value:
            return False

        patterns = [
            r"^\d{1,4}$",                     # 12
            r"^[-—_]\s*\d{1,4}\s*[-—_]$",     # - 12 -
            r"^第\s*\d{1,4}\s*页$",            # 第12页
            r"^page\s*\d{1,4}$",              # page 12
            r"^\d{1,4}\s*/\s*\d{1,4}$",       # 12/100
        ]
        lowered = value.lower()
        return any(re.match(pattern, lowered) for pattern in patterns)

    @staticmethod
    def _looks_like_structural_heading(line: str) -> bool:
        value = str(line or "").strip()
        if not value:
            return False

        return bool(
            re.match(r"^第[一二三四五六七八九十百千万零〇\d]+[章节条]", value)
            or re.match(r"^[一二三四五六七八九十]+、", value)
            or re.match(r"^[（(][一二三四五六七八九十\d]+[）)]", value)
            or re.match(r"^\d+[.、）)]", value)
        )

    @staticmethod
    def _detect_repeated_header_footer_lines(pages_lines: List[List[str]]) -> Set[str]:
        if not pages_lines:
            return set()

        page_count = len(pages_lines)
        if page_count < 3:
            return set()

        line_page_hits: Dict[str, int] = {}
        for lines in pages_lines:
            # 仅统计每页前后几行，避免误删正文中重复短句
            candidates = lines[:4] + lines[-4:] if len(lines) > 8 else lines
            seen_in_page = set(candidates)
            for line in seen_in_page:
                line_page_hits[line] = line_page_hits.get(line, 0) + 1

        threshold = max(3, int(page_count * 0.45))
        repeated = set()
        for line, hits in line_page_hits.items():
            if hits < threshold:
                continue
            if len(line) > 24:
                continue
            if DocumentProcessor._looks_like_page_number_line(line):
                repeated.add(line)
                continue
            # 保护章/节/条等目录型标题
            if DocumentProcessor._looks_like_structural_heading(line):
                continue
            repeated.add(line)

        return repeated

    @staticmethod
    def _should_merge_pdf_lines(prev_line: str, curr_line: str) -> bool:
        prev = str(prev_line or "").strip()
        curr = str(curr_line or "").strip()
        if not prev or not curr:
            return False

        # 新段落/新标题通常不合并
        if DocumentProcessor._looks_like_structural_heading(curr):
            return False
        if DocumentProcessor._looks_like_page_number_line(curr):
            return False

        # 句号等终止符结尾，倾向新句新行
        if re.search(r"[。！？!?；;：:]$", prev):
            return False

        # 如果上一行明显是标题，避免把正文拼到标题行
        if DocumentProcessor._looks_like_structural_heading(prev):
            return False

        # 其余情况默认合并，可显著减少“同一句被拆成两行”
        return True

    @staticmethod
    def _clean_pdf_page_lines(lines: List[str], repeated_header_footer: Set[str]) -> List[str]:
        filtered: List[str] = []
        for line in lines:
            if line in repeated_header_footer:
                continue
            if DocumentProcessor._looks_like_page_number_line(line):
                continue
            filtered.append(line)

        if not filtered:
            return []

        merged: List[str] = []
        for line in filtered:
            if not merged:
                merged.append(line)
                continue
            if DocumentProcessor._should_merge_pdf_lines(merged[-1], line):
                merged[-1] = f"{merged[-1]}{line}"
            else:
                merged.append(line)
        return merged
    
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


def process_uploaded_documents(
    file_paths: List[str],
    doc_type: str = 'internal_regulation',
    title: str = None,
    original_filenames: List[str] = None,
    error_collector: List[Dict[str, str]] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
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
        filename = os.path.basename(file_path)
        
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

            if extra_metadata:
                doc_obj.update({k: v for k, v in extra_metadata.items() if v is not None})
            
            documents.append(doc_obj)
            logger.info(f"文档 {filename} 处理完成，字符数: {len(content)}, 类型: {doc_type}")
            
        except Exception as e:
            logger.error(f"处理文档 {file_path} 时发生错误: {e}")
            if error_collector is not None:
                error_collector.append({
                    "filename": filename,
                    "error": str(e),
                })
            continue  # 继续处理其他文档
    
    logger.info(f"所有文档处理完成，成功处理 {len(documents)} 个文档")
    return documents
