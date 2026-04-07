import os
import logging
import re
from typing import Dict, Any, List, Optional, Set
from docx import Document
import pdfplumber
import chardet

try:
    import fitz
except ImportError:  # pragma: no cover - optional dependency
    fitz = None

try:
    from rapidocr_onnxruntime import RapidOCR
except ImportError:  # pragma: no cover - optional dependency
    RapidOCR = None


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
    
    ENTERPRISE_ACCOUNTING_STANDARDS_PROFILE = "enterprise_accounting_standards_compendium"
    OCR_RENDER_SCALE = 2.0
    _ocr_engine = None
    _ocr_engine_initialized = False

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
    def detect_ingest_profile(filename: str = "", title: str = "") -> Optional[str]:
        source = f"{filename} {title}".strip()
        normalized = re.sub(r"\s+", "", source)
        if not normalized:
            return None

        if (
            "企业会计准则" in normalized
            and (
                "应用指南" in normalized
                or "2006-2018" in normalized
                or "20062018" in normalized
            )
        ):
            return DocumentProcessor.ENTERPRISE_ACCOUNTING_STANDARDS_PROFILE

        return None

    @staticmethod
    def load_document(
        file_path: str,
        doc_type: str = 'default',
        source_name: str = "",
        ingest_profile: Optional[str] = None,
    ) -> str:
        """
        根据文件类型加载文档内容
        :param file_path: 文件路径
        :param doc_type: 文档类型，审计问题类型会特殊处理表格
        :return: 文档文本内容
        """
        file_type = DocumentProcessor.detect_file_type(file_path)
        logger.info(f"检测到文件类型: {file_type}，文件路径: {file_path}")
        effective_profile = ingest_profile or DocumentProcessor.detect_ingest_profile(source_name or file_path, source_name)
        
        if file_type == 'pdf':
            return DocumentProcessor._load_pdf(
                file_path,
                is_audit_issue=(doc_type == 'audit_issue'),
                ingest_profile=effective_profile,
            )
        elif file_type == 'docx':
            return DocumentProcessor._load_docx(file_path)
        elif file_type == 'txt':
            return DocumentProcessor._load_txt(file_path)
        else:
            raise ValueError(f"不支持的文件类型: {file_type}")
    
    @staticmethod
    def _load_pdf(file_path: str, is_audit_issue: bool = False, ingest_profile: Optional[str] = None) -> str:
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
                    if ingest_profile == DocumentProcessor.ENTERPRISE_ACCOUNTING_STANDARDS_PROFILE:
                        normal_mode_pages = DocumentProcessor._strip_leading_toc_pages_for_profile(normal_mode_pages)
                    repeated_header_footer = DocumentProcessor._detect_repeated_header_footer_lines(normal_mode_pages)
                    for page_num, lines in enumerate(normal_mode_pages):
                        page_tag = f"[[PAGE:{page_num + 1}]]"
                        cleaned_lines = DocumentProcessor._clean_pdf_page_lines(lines, repeated_header_footer)
                        if cleaned_lines:
                            text_parts.append(f"{page_tag}\n" + "\n".join(cleaned_lines))
                        else:
                            text_parts.append(page_tag)
            
            full_text = "\n".join(text_parts)
            if not DocumentProcessor.has_meaningful_text(full_text):
                ocr_text = DocumentProcessor._load_pdf_with_ocr(file_path)
                if DocumentProcessor.has_meaningful_text(ocr_text):
                    logger.info("PDF文本抽取为空，已使用OCR回退: %s", file_path)
                    full_text = ocr_text
            logger.info(f"PDF文档加载完成，总内容长度: {len(full_text)}")
            return full_text
            
        except Exception as e:
            logger.error(f"加载PDF文档失败: {e}")
            raise

    @classmethod
    def _get_ocr_engine(cls):
        if cls._ocr_engine_initialized:
            return cls._ocr_engine

        cls._ocr_engine_initialized = True
        if fitz is None or RapidOCR is None:
            logger.warning("OCR依赖不可用，扫描版PDF将无法自动识别")
            cls._ocr_engine = None
            return None

        try:
            cls._ocr_engine = RapidOCR()
            logger.info("RapidOCR初始化完成")
        except Exception as exc:  # noqa: BLE001
            logger.warning("RapidOCR初始化失败: %s", exc)
            cls._ocr_engine = None
        return cls._ocr_engine

    @classmethod
    def _load_pdf_with_ocr(cls, file_path: str) -> str:
        ocr_engine = cls._get_ocr_engine()
        if ocr_engine is None or fitz is None:
            return ""

        text_parts: List[str] = []
        try:
            with fitz.open(file_path) as pdf:
                for page_num in range(pdf.page_count):
                    page_tag = f"[[PAGE:{page_num + 1}]]"
                    page = pdf.load_page(page_num)
                    pix = page.get_pixmap(matrix=fitz.Matrix(cls.OCR_RENDER_SCALE, cls.OCR_RENDER_SCALE), alpha=False)
                    result, _ = ocr_engine(pix.tobytes("png"))

                    lines: List[str] = []
                    for item in result or []:
                        if not isinstance(item, (list, tuple)) or len(item) < 2:
                            continue
                        text = str(item[1] or "").strip()
                        if text:
                            lines.append(text)

                    if lines:
                        text_parts.append(f"{page_tag}\n" + "\n".join(lines))
                    else:
                        text_parts.append(page_tag)

            return "\n".join(text_parts)
        except Exception as exc:  # noqa: BLE001
            logger.warning("OCR识别PDF失败: %s | %s", file_path, exc)
            return ""

    @staticmethod
    def has_meaningful_text(content: str) -> bool:
        cleaned = re.sub(r"\[\[PAGE:\d+\]\]", " ", str(content or ""))
        cleaned = re.sub(r"\s+", "", cleaned)
        if not cleaned:
            return False
        return any(ch.isalnum() for ch in cleaned)

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
            or re.match(r"^企业会计准则第[一二三四五六七八九十百千万零〇两\d]+号", value)
            or re.match(r"^企业会计准则应用指南", value)
            or re.match(r"^[一二三四五六七八九十]+、", value)
            or re.match(r"^[（(][一二三四五六七八九十\d]+[）)]", value)
            or re.match(r"^\d+[.、）)]", value)
        )

    @staticmethod
    def _looks_like_toc_entry_line(line: str) -> bool:
        value = str(line or "").strip()
        if not value:
            return False

        compact = re.sub(r"\s+", "", value)
        if re.search(r"[.．…·•]{2,}\d{1,4}$", compact):
            return True
        if re.match(r"^(第[一二三四五六七八九十百千万零〇两\d]+[章节条]|企业会计准则第[一二三四五六七八九十百千万零〇两\d]+号)", compact) and re.search(r"\d{1,4}$", compact):
            return True
        return False

    @staticmethod
    def _looks_like_toc_page(lines: List[str]) -> bool:
        normalized_lines = [str(line or "").strip() for line in (lines or []) if str(line or "").strip()]
        if not normalized_lines:
            return False

        first_line = re.sub(r"\s+", "", normalized_lines[0])
        if first_line in {"目录", "目录:", "目录：", "目录", "目录:", "目录："}:
            return True

        toc_like_count = sum(1 for line in normalized_lines if DocumentProcessor._looks_like_toc_entry_line(line))
        structural_count = sum(1 for line in normalized_lines if DocumentProcessor._looks_like_structural_heading(line))
        return toc_like_count >= 5 or (toc_like_count >= 3 and structural_count >= 6)

    @staticmethod
    def _strip_leading_toc_pages_for_profile(pages_lines: List[List[str]], max_scan_pages: int = 8) -> List[List[str]]:
        if not pages_lines:
            return pages_lines

        skip_count = 0
        upper_bound = min(len(pages_lines), max_scan_pages)
        for idx in range(upper_bound):
            if DocumentProcessor._looks_like_toc_page(pages_lines[idx]):
                skip_count += 1
                continue
            break

        if skip_count > 0:
            logger.info("企业会计准则专用入库规则生效，跳过前 %s 页目录页", skip_count)
            return [[] if idx < skip_count else lines for idx, lines in enumerate(pages_lines)]
        return pages_lines

    @staticmethod
    def _looks_like_article_reference_lead(line: str) -> bool:
        value = str(line or "").strip()
        if not value:
            return False

        match = re.match(r"^(第[一二三四五六七八九十百千万零〇两\d]+条)", value)
        if not match:
            return False

        rest = value[match.end():].strip()
        if not rest:
            return False

        if re.match(r"^[、，,；;：:]\s*第[一二三四五六七八九十百千万零〇两\d]+条", rest):
            return True
        if re.match(r"^(和|及|与|或者|或)\s*第[一二三四五六七八九十百千万零〇两\d]+条", rest):
            return True
        if re.match(r"^(规定的|规定|所称|所列|之一|之二|之三|情形|办理|执行)", rest):
            return True

        return False

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
            # 章/节/条等结构标题通常不删除，但如果它们在大量页面边缘反复出现，
            # 更可能是页眉/页脚中的“当前条款提示”而非正文，应一并清理。
            if DocumentProcessor._looks_like_structural_heading(line):
                structural_threshold = max(3, int(page_count * 0.6))
                if hits >= structural_threshold and len(line) <= 18:
                    repeated.add(line)
                continue
            repeated.add(line)

        return repeated

    @staticmethod
    def _should_merge_pdf_lines(prev_line: str, curr_line: str) -> bool:
        prev = str(prev_line or "").strip()
        curr = str(curr_line or "").strip()
        if not prev or not curr:
            return False

        # 句号等终止符结尾，倾向新句新行
        if re.search(r"[。！？!?；;：:]$", prev):
            return False

        # 如果上一行明显是标题，避免把正文拼到标题行
        if DocumentProcessor._looks_like_structural_heading(prev):
            return False

        if DocumentProcessor._looks_like_page_number_line(curr):
            return False

        # 行首“第X条”如果明显是正文中的条文引用，优先并回上一行。
        if DocumentProcessor._looks_like_article_reference_lead(curr):
            return True

        # 新段落/新标题通常不合并
        if DocumentProcessor._looks_like_structural_heading(curr):
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

            resolved_title = title or filename
            ingest_profile = DocumentProcessor.detect_ingest_profile(filename, resolved_title)
            
            # 加载文档内容
            content = DocumentProcessor.load_document(
                file_path,
                doc_type=doc_type,
                source_name=filename,
                ingest_profile=ingest_profile,
            )
            if not DocumentProcessor.has_meaningful_text(content):
                file_type = DocumentProcessor.detect_file_type(filename)
                if file_type == 'pdf':
                    raise ValueError("未从PDF中提取到可用文本，可能是扫描版/图片版PDF，请先OCR后再上传")
                raise ValueError("文档未提取到可用文本内容")
            
            # 创建文档对象
            doc_obj = {
                'doc_id': f'doc_{idx}',
                'filename': filename,
                'file_path': file_path,
                'file_type': DocumentProcessor.detect_file_type(filename), # 使用文件名检测类型更准确
                'doc_type': doc_type,
                'title': resolved_title,
                'text': content,
                'char_count': len(content)
            }
            if ingest_profile:
                doc_obj['ingest_profile'] = ingest_profile

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
