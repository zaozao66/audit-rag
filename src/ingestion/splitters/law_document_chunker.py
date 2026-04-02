import re
import logging
from typing import List, Dict, Any
from src.ingestion.splitters.document_chunker import DocumentChunker

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class LawDocumentChunker(DocumentChunker):
    """
    法规制度文档分块器
    按照法规的层级结构进行智能分块，保持条款的完整性
    """
    
    def __init__(self, chunk_size: int = 1024, overlap: int = 50):
        super().__init__(chunk_size=chunk_size, overlap=overlap)
        
        # 法规文档常见的层级模式
        self.preamble_patterns = [
            r'^(序\s*言|前\s*言)\s*$',  # 序言/前言（可能含空格）
        ]

        self.chapter_patterns = [
            r'^第[一二三四五六七八九十百千万零〇两\d]+章\s*[^\n]*',  # 第X章
            r'^第[一二三四五六七八九十百千万零〇两\d]+节\s*[^\n]*',  # 第X节
            r'^第[一二三四五六七八九十百千万零〇两\d]+条\s*[^\n]*',  # 第X条
            r'^\d+\.\d+\.\d+\s*[^\n]*',  # 1.2.3 格式
            r'^\d+\.\d+\s*[^\n]*',       # 1.2 格式
            r'^\d+\.\s*[^\n]*',          # 1. 格式
            r'^[\d一二三四五六七八九十百千万零〇两]+、\s*[^\n]*',   # 一、格式
        ]
        
        # 条款模式
        self.article_patterns = [
            r'^第[一二三四五六七八九十百千万零〇两\d]+条\s*[^\n]*',
            r'^第[一二三四五六七八九十百千万零〇两\d]+条[^\n]*',
            r'^\d+\.\d+\.\d+\s*[^\n]*',
            r'^\d+\.\d+\s*[^\n]*',
        ]
        
        # 子条款模式（这些应该跟随主条款，而不是单独成块）
        self.sub_article_patterns = [
            r'^（[一二三四五六七八九十百千万零〇两\d]+）\s*[^\n]*',  # （一）格式
            r'^\([一二三四五六七八九十百千万零〇两\d]+\)\s*[^\n]*',  # (一) 格式
            r'^（[①②③④⑤⑥⑦⑧⑨⑩]+\）\s*[^\n]*',      # （①）格式
            r'^\([①②③④⑤⑥⑦⑧⑨⑩]+\)\s*[^\n]*',       # (①) 格式
        ]
        
        # 组合所有模式
        self.all_patterns = self.preamble_patterns + self.chapter_patterns + self.sub_article_patterns
        self._page_tag_pattern = re.compile(r"\[\[PAGE:\d+\]\]")

    
    def chunk_law_document(self, document: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        专门针对法规文档的分块方法
        :param document: 文档对象
        :return: 分块后的文档列表
        """
        text = document['text']
        filename = document.get('filename', 'unknown')
            
        logger.info(f"开始按法规结构分块文档: {filename}")
        ingest_profile = str(document.get('ingest_profile', '') or '').strip()
            
        # 按行分割文本，并对PDF抽取常见的重复字伪影做归一化
        lines = [self._normalize_extracted_line(line) for line in text.split('\n')]
            
        # 识别章节结构
        sections = self._identify_sections(lines, ingest_profile=ingest_profile)
            
        # 构建分块
        chunks = []
        current_section_path = []
            
        for section in sections:
            section_type = section['type']
            section_content = section['content']
            section_header = section['header']

            # 跳过子条款的处理，因为它们已经被合并到父级中
            if section_type == 'sub_article':
                continue

            # 计算本块的章节路径（避免“路径标题 + 当前标题”重复）
            chunk_section_path = current_section_path.copy()
            if section_type == 'chapter' and section_header:
                chunk_section_path = [section_header]
            elif section_type == 'section' and section_header:
                chapter_context = self._extract_chapter_context(current_section_path)
                chunk_section_path = chapter_context + [section_header]

            # 将章节标题添加到内容前面
            # chapter 不继承上一章节前缀；section 仅继承章级前缀；article/content 继承当前路径
            if section_type == 'chapter':
                section_title = ''
            elif section_type == 'section':
                section_title = ' '.join(chunk_section_path[:-1])
            else:
                section_title = ' '.join(current_section_path)
            if section_header and section_header != section_title:
                # 避免重复标题，只添加不重复的部分
                if section_content.startswith(section_header):
                    # 如果内容以标题开头，去除重复
                    clean_content = section_content[len(section_header):].lstrip('\n')
                    full_content = f"{section_title}\n{section_header}\n{clean_content}".strip()
                else:
                    full_content = f"{section_title}\n{section_header}\n{section_content}".strip()
            elif section_title:
                # 检查内容是否已包含章节标题
                if not section_content.startswith(section_title):
                    full_content = f"{section_title}\n{section_content}".strip()
                else:
                    full_content = section_content.strip()
            else:
                full_content = section_content.strip()
                
            # 检查内容长度：仅对无结构的 content 块做拆分；章/节/条保持结构语义与目录稳定
            should_split = len(full_content) > self.chunk_size and section_type == 'content'
            if should_split:
                sub_chunks = self._split_large_content(full_content, chunk_section_path, document)
                if sub_chunks:
                    chunks.extend(sub_chunks)
                    continue
                # 兜底：分割失败时回退原块，避免内容丢失（曾出现“第五条”被吞）
                logger.warning(f"大块内容分割后为空，回退原块: {section_header[:30] if section_header else 'unknown'}")

            skip_current_chunk = False
            # 过滤掉只有标题而没有实质内容的块
            # 检查是否只是标题而没有实际内容
            if section_header:
                # 移除标题部分，得到除标题和章节路径外的内容
                content_without_header = full_content.replace(section_header, '', 1).strip()
                                
                # 如果当前section_path不为空，也从内容中移除章节路径的标题（避免路径信息影响判断）
                for path_header in chunk_section_path:
                    content_without_header = content_without_header.replace(path_header, '', 1)
                
                content_without_header = self._strip_page_tags(content_without_header).strip()
                                
                # 移除可能的注释（如 # 这个只有标题没有内容）
                content_without_comments = re.sub(r'#.*$', '', content_without_header, flags=re.MULTILINE).strip()
                                
                # 检查除标题外的内容是否为空或只有很少的有效字符
                # 计算有意义的字符（中文、英文字母、数字、标点符号）
                meaningful_chars = sum(1 for c in content_without_comments if c.isalnum() or c in '，。！？；：、""\'\'（）【】[]《》〈〉「」『』…—')
                                    
                # 特殊处理：如果是章节类型（chapter/section）且没有实质性内容，则跳过
                if section_type in ['chapter', 'section'] and meaningful_chars < 5:
                    logger.debug(f"跳过仅有标题或内容过少的章节: {section_header}")
                    skip_current_chunk = True
                                    
                # 对于article类型，如果标题后没有实质内容（如"第七条"后面没有任何内容），也跳过
                if section_type == 'article':
                    # 检查是否是简单序号标题（如"第X条"）且内容主要是注释
                    is_simple_numbered_article = re.match(r'^第[一二三四五六七八九十百千万零〇两\d]+条', section_header.strip())
                    
                    if is_simple_numbered_article and meaningful_chars < 5:
                        logger.debug(f"跳过无实质内容的简单条款: {section_header}")
                        skip_current_chunk = True

                    # 检查内容是否主要是注释
                    is_mainly_comment = '#' in section_header and meaningful_chars < 5
                    
                    # 如果是简单的序号条款且主要内容是注释，则跳过
                    if is_simple_numbered_article and is_mainly_comment:
                        logger.debug(f"跳过内容主要是注释的简单条款: {section_header}")
                        skip_current_chunk = True

            if not skip_current_chunk:
                chunk = {
                    'doc_id': document.get('doc_id', ''),
                    'filename': filename,
                    'file_type': document.get('file_type', ''),
                    'doc_type': document.get('doc_type', 'internal_regulation'),  # 添加文档类型
                    'title': document.get('title', ''),  # 添加标题
                    'text': full_content,
                    'semantic_boundary': section_type,
                    'section_path': chunk_section_path.copy(),
                    'header': section_header,
                    'char_count': len(full_content)
                }
                chunks.append(chunk)

            # 处理完当前块后再更新路径，避免当前标题重复进入前缀
            if section_type == 'chapter':
                current_section_path = [section_header] if section_header else []
            elif section_type == 'section':
                chapter_context = self._extract_chapter_context(current_section_path)
                current_section_path = chapter_context + [section_header] if section_header else chapter_context
            
        chunks = self._filter_suspicious_article_chunks(chunks)
        logger.info(f"法规文档分块完成，共生成 {len(chunks)} 个文本块")
        return chunks

    def _extract_chapter_context(self, section_path: List[str]) -> List[str]:
        """
        提取章节上下文中的“章”层级，避免“节”被错误叠加为上一个节的子级。
        """
        for header in section_path:
            normalized = str(header or "").strip()
            if re.match(r'^第[一二三四五六七八九十百千万零〇两\d]+章', normalized):
                return [normalized]
        return []
    
    @staticmethod
    def _looks_like_profile_toc_entry(line: str) -> bool:
        compact = re.sub(r'\s+', '', str(line or '').strip())
        if not compact:
            return False
        if re.search(r'[.．…·•]{2,}\d{1,4}$', compact):
            return True
        if compact.endswith(tuple(str(i) for i in range(10))) and re.match(r'^企业会计准则第[一二三四五六七八九十百千万零〇两\d]+号', compact):
            return True
        return False

    @staticmethod
    def _match_profile_root_heading(line: str, ingest_profile: str) -> tuple:
        if ingest_profile != 'enterprise_accounting_standards_compendium':
            return None, ''

        stripped_line = str(line or '').strip()
        if not stripped_line or LawDocumentChunker._looks_like_profile_toc_entry(stripped_line):
            return None, ''

        compact = re.sub(r'[\s《》<>]', '', stripped_line)
        if re.match(r'^企业会计准则第[一二三四五六七八九十百千万零〇两\d]+号', compact):
            return 'chapter', stripped_line
        if compact.startswith('企业会计准则应用指南'):
            return 'chapter', stripped_line
        return None, ''

    def _identify_sections(self, lines: List[str], ingest_profile: str = '') -> List[Dict[str, Any]]:
        """
        识别文档中的章节结构
        :param lines: 文档行列表
        :return: 章节列表
        """
        sections = []
        
        for line in lines:
            # 检查是否是章节标题
            section_type, header = self._check_section_header(line, ingest_profile=ingest_profile)
            
            if section_type:
                if section_type == 'sub_article':
                    # 如果是子条款，将其添加到上一个章节内容中（而不是作为新章节）
                    if sections and sections[-1]['type'] in ['article']:
                        # 将子条款添加到上一个条款
                        sections[-1]['content'] += header + '\n'
                    else:
                        # 如果前面没有合适的父条款，则作为普通内容添加到当前章节
                        if sections:
                            sections[-1]['content'] += line + '\n'
                        else:
                            # 如果还没有章节，创建一个普通内容章节
                            sections.append({
                                'type': 'content',
                                'header': '',
                                'content': line + '\n'
                            })
                else:
                    # 创建新的章节，无论是章节还是条款
                    sections.append({
                        'type': section_type,
                        'header': header.strip(),
                        'content': line + '\n'
                    })
            else:
                # 添加内容到最新章节
                if sections:
                    sections[-1]['content'] += line + '\n'
                else:
                    # 如果还没有章节，创建一个普通内容章节
                    sections.append({
                        'type': 'content',
                        'header': '',
                        'content': line + '\n'
                    })
        
        return sections
    
    def _check_section_header(self, line: str, ingest_profile: str = '') -> tuple:
        """
        检查行是否为章节标题
        :param line: 文本行
        :return: (章节类型, 章节标题) 或 (None, '')
        """
        stripped_line = line.strip()
        
        # 跳过空行
        if not stripped_line:
            return None, ''

        profile_section_type, profile_header = self._match_profile_root_heading(stripped_line, ingest_profile)
        if profile_section_type:
            return profile_section_type, profile_header
        
        # 检查子条款模式（优先检查，因为它们应该跟随父条款）
        for pattern in self.sub_article_patterns:
            match = re.match(pattern, stripped_line)
            if match:
                header = match.group(0)
                return 'sub_article', header

        # 检查序言/前言（作为章节层级处理，确保独立成块）
        for pattern in self.preamble_patterns:
            match = re.match(pattern, stripped_line)
            if match:
                normalized = re.sub(r'\s+', '', match.group(1))
                return 'chapter', normalized
        
        # 检查章节模式
        for pattern in self.chapter_patterns:
            match = re.match(pattern, stripped_line)
            if match:
                header = match.group(0)
                if self._looks_like_article_reference_heading(stripped_line):
                    return None, ''
                if any(re.match(p, header) for p in self.article_patterns):
                    return 'article', self._extract_article_heading_token(stripped_line)
                elif '章' in header:
                    return 'chapter', header
                elif '节' in header:
                    return 'section', header
                else:
                    return 'article', header
        
        return None, ''
    
    def _split_large_content(self, content: str, section_path: List[str], document: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        将大块内容进一步分割，同时保持上下文信息
        :param content: 大块内容
        :param section_path: 当前章节路径
        :return: 分割后的小块列表
        """
        chunks = []
        
        # 按段落分割，但保留章节标题在每个块中
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
        
        if not paragraphs:
            return []  # 如果没有段落，返回空列表
        
        # 确定章节标题部分（前两行通常是标题）
        title_part = ""
        content_start_idx = 0
        
        # 查找标题部分（章节标题和条款标题）
        for i, para in enumerate(paragraphs):
            if any(re.match(pattern, para.strip()) for pattern in self.chapter_patterns):
                title_part += para + '\n\n'
                content_start_idx = i + 1
            else:
                break
        
        current_chunk = title_part
        current_size = len(current_chunk)
        
        # 处理剩余内容
        for i in range(content_start_idx, len(paragraphs)):
            paragraph = paragraphs[i]
            paragraph_with_separator = paragraph + '\n\n'
            paragraph_size = len(paragraph_with_separator)
            
            if current_size + paragraph_size > self.chunk_size and current_chunk.strip() != title_part.strip():
                # 保存当前块
                chunk = {
                    'doc_id': '',
                    'filename': 'law_document',
                    'file_type': 'txt',
                    'doc_type': document.get('doc_type', 'internal_regulation'),  # 添加文档类型
                    'title': document.get('title', ''),  # 添加标题
                    'text': current_chunk.strip(),
                    'semantic_boundary': 'sub_article',
                    'section_path': section_path.copy(),
                    'header': section_path[-1] if section_path else '',
                    'char_count': len(current_chunk)
                }
                chunks.append(chunk)
                
                # 开始新块，包含章节标题
                current_chunk = title_part + paragraph_with_separator
                current_size = len(title_part) + paragraph_size
            else:
                current_chunk += paragraph_with_separator
                current_size += paragraph_size
        
        # 添加最后一块
        if current_chunk.strip() and len(current_chunk.strip()) > len(title_part.strip()):
            chunk = {
                'doc_id': '',
                'filename': 'law_document',
                'file_type': 'txt',
                'doc_type': document.get('doc_type', 'internal_regulation'),  # 添加文档类型
                'title': document.get('title', ''),  # 添加标题
                'text': current_chunk.strip(),
                'semantic_boundary': 'sub_article',
                'section_path': section_path.copy(),
                'header': section_path[-1] if section_path else '',
                'char_count': len(current_chunk)
            }
            chunks.append(chunk)
        
        return chunks
    
    def chunk_documents(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        重写父类方法，对法规文档使用专门的分块逻辑
        """
        all_chunks = []
        
        for doc in documents:
            # 如果显式指定了使用法规分块器，或者自动检测是法规文档，则使用专门逻辑
            # 注意：如果是从 SmartChunker 调用的，我们会通过 _is_law_document 判断
            # 但如果是 RAGProcessor 直接持有的 LawDocumentChunker，则强制使用
            if self.__class__ == LawDocumentChunker or self._is_law_document(doc):
                logger.info(f"使用法规分块逻辑处理: {doc.get('filename', 'unknown')}")
                chunks = self.chunk_law_document(doc)
            else:
                # 对非法规文档使用普通分块方法
                logger.info(f"使用普通分块器: {doc.get('filename', 'unknown')}")
                chunks = super().chunk_documents([doc])
            
            all_chunks.extend(chunks)
        
        return all_chunks
    
    def _is_law_document(self, document: Dict[str, Any]) -> bool:
        """
        判断是否为法规文档
        :param document: 文档对象
        :return: 是否为法规文档
        """
        text = document.get('text', '').lower()
        filename = document.get('filename', '').lower()
        
        # 检查关键词
        law_keywords = [
            '法', '条例', '规定', '办法', '章程', '规则', '细则', '制度', '政策',
            'regulation', 'rule', 'policy', 'statute', 'ordinance', 'bylaw',
            '法律', '法规', '行政法规', '部门规章', '国家标准', '行业标准'
        ]
        
        # 检查是否包含法规关键词
        for keyword in law_keywords:
            if keyword in text[:500] or keyword in filename:  # 检查前500个字符和文件名
                return True
        
        # 检查是否包含法规结构模式
        for pattern in self.chapter_patterns:
            if re.search(pattern, text[:2000]):  # 检查前2000个字符
                return True
        
        return False

    @staticmethod
    def _is_cjk_char(char: str) -> bool:
        """判断是否为常见中文字符"""
        return '\u4e00' <= char <= '\u9fff'

    def _normalize_extracted_line(self, line: str) -> str:
        """
        归一化PDF抽取常见伪影：
        1. 去除首尾空白
        2. 在“重复字占比明显偏高”时，压缩连续重复中文字符
        """
        stripped = line.strip()
        if not stripped:
            return ''

        # 对“第...条/章/节”前缀做定向归一化，避免误伤正文中的合法叠字
        heading_prefix_match = re.match(r'^(第[^\s，。；：、,.:;]{1,30})', stripped)
        if heading_prefix_match:
            heading_prefix = heading_prefix_match.group(1)
            normalized_heading_prefix = re.sub(r'([\u4e00-\u9fff])\1+', r'\1', heading_prefix)
            if normalized_heading_prefix != heading_prefix:
                stripped = normalized_heading_prefix + stripped[len(heading_prefix):]

        cjk_count = sum(1 for ch in stripped if self._is_cjk_char(ch))
        duplicate_pairs = sum(
            1
            for i in range(len(stripped) - 1)
            if stripped[i] == stripped[i + 1] and self._is_cjk_char(stripped[i])
        )

        # 阈值设计：至少2处重复且重复占比>=10%，再做压缩，避免误伤正常词
        if cjk_count > 0 and duplicate_pairs >= 2 and (duplicate_pairs / cjk_count) >= 0.10:
            stripped = re.sub(r'([\u4e00-\u9fff])\1+', r'\1', stripped)

        return stripped

    def _strip_page_tags(self, text: str) -> str:
        cleaned = self._page_tag_pattern.sub("", str(text or ""))
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    @staticmethod
    def _extract_article_heading_token(line: str) -> str:
        stripped = str(line or "").strip()
        match = re.match(r'^(第[一二三四五六七八九十百千万零〇两\d]+条)', stripped)
        if match:
            return match.group(1)
        return stripped

    @staticmethod
    def _looks_like_article_reference_heading(line: str) -> bool:
        stripped = str(line or "").strip()
        if not stripped:
            return False

        match = re.match(r'^(第[一二三四五六七八九十百千万零〇两\d]+条)', stripped)
        if not match:
            return False

        rest = stripped[match.end():].strip()
        if not rest:
            return False

        if re.match(r'^[、，,；;：:]\s*第[一二三四五六七八九十百千万零〇两\d]+条', rest):
            return True
        if re.match(r'^(和|及|与|或者|或)\s*第[一二三四五六七八九十百千万零〇两\d]+条', rest):
            return True

        return False

    def _extract_chunk_body_text(self, chunk: Dict[str, Any]) -> str:
        text = str(chunk.get('text', '') or '')
        header = str(chunk.get('header', '') or '').strip()
        section_path = [str(item).strip() for item in (chunk.get('section_path', []) or []) if str(item).strip()]
        cleaned = self._strip_page_tags(text)
        if header:
            cleaned = cleaned.replace(header, '', 1).strip()
        for path_header in section_path:
            cleaned = cleaned.replace(path_header, '', 1).strip()
        cleaned = re.sub(r'#.*$', '', cleaned, flags=re.MULTILINE).strip()
        return cleaned

    @staticmethod
    def _looks_like_reference_style_body(text: str) -> bool:
        stripped = str(text or '').strip()
        if not stripped:
            return False

        if re.match(r'^[、，,；;：:]\s*第[一二三四五六七八九十百千万零〇两\d]+条', stripped):
            return True
        if re.match(r'^(和|及|与|或者|或)\s*第[一二三四五六七八九十百千万零〇两\d]+条', stripped):
            return True
        if re.match(r'^(规定的|规定|所称|所列|之一|之二|之三|情形|办理|执行|适用|处理|追究)', stripped):
            return True

        return False

    @staticmethod
    def _extract_article_number_from_header(header: str) -> int:
        token = str(header or "").strip()
        if not token:
            return -1
        match = re.match(r'^第([一二三四五六七八九十百千万零〇两\d]+)条', token)
        if not match:
            return -1
        raw = str(match.group(1) or "").strip()
        if raw.isdigit():
            return int(raw)

        digit_map = {
            "零": 0,
            "〇": 0,
            "一": 1,
            "二": 2,
            "两": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
        }
        unit_map = {"十": 10, "百": 100, "千": 1000, "万": 10000}

        if all(ch in digit_map for ch in raw):
            return int("".join(str(digit_map[ch]) for ch in raw))

        total = 0
        section = 0
        number = 0
        seen = False
        for ch in raw:
            if ch in digit_map:
                number = digit_map[ch]
                seen = True
                continue
            if ch in unit_map:
                seen = True
                unit = unit_map[ch]
                if unit == 10000:
                    section = (section + number) * unit
                    total += section
                    section = 0
                    number = 0
                else:
                    if number == 0:
                        number = 1
                    section += number * unit
                    number = 0
                continue
            return -1

        if not seen:
            return -1
        return total + section + number

    def _body_meaningful_chars(self, chunk: Dict[str, Any]) -> int:
        cleaned = self._extract_chunk_body_text(chunk)
        return sum(1 for c in cleaned if c.isalnum() or c in '，。！？；：、""\'\'（）【】[]《》〈〉「」『』…—')

    def _filter_suspicious_article_chunks(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if len(chunks) < 3:
            return chunks

        filtered: List[Dict[str, Any]] = []
        for idx, chunk in enumerate(chunks):
            if chunk.get('semantic_boundary') != 'article':
                filtered.append(chunk)
                continue

            current_number = self._extract_article_number_from_header(chunk.get('header', ''))
            if current_number < 0:
                filtered.append(chunk)
                continue

            prev_number = -1
            next_number = -1
            for prev_idx in range(idx - 1, -1, -1):
                if chunks[prev_idx].get('semantic_boundary') == 'article':
                    prev_number = self._extract_article_number_from_header(chunks[prev_idx].get('header', ''))
                    break
            for next_idx in range(idx + 1, len(chunks)):
                if chunks[next_idx].get('semantic_boundary') == 'article':
                    next_number = self._extract_article_number_from_header(chunks[next_idx].get('header', ''))
                    break

            body_chars = self._body_meaningful_chars(chunk)
            body_text = self._extract_chunk_body_text(chunk)
            looks_like_reference_body = self._looks_like_reference_style_body(body_text)
            is_regression_noise = (
                prev_number > 0
                and next_number > 0
                and current_number < prev_number
                and next_number == prev_number + 1
                and (body_chars < 12 or looks_like_reference_body)
            )
            if is_regression_noise:
                logger.warning(
                    "跳过疑似PDF抽取伪影条款: current=%s prev=%s next=%s header=%s body_chars=%s reference_like=%s",
                    current_number,
                    prev_number,
                    next_number,
                    chunk.get('header', ''),
                    body_chars,
                    looks_like_reference_body,
                )
                continue

            filtered.append(chunk)

        return filtered
