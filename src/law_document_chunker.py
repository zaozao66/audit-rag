import re
import logging
from typing import List, Dict, Any
from document_chunker import DocumentChunker

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
        self.chapter_patterns = [
            r'^第[一二三四五六七八九十\d]+章\s*[^\n]*',  # 第X章
            r'^第[一二三四五六七八九十\d]+节\s*[^\n]*',  # 第X节
            r'^第[一二三四五六七八九十\d]+条\s*[^\n]*',  # 第X条
            r'^\d+\.\d+\.\d+\s*[^\n]*',  # 1.2.3 格式
            r'^\d+\.\d+\s*[^\n]*',       # 1.2 格式
            r'^\d+\.\s*[^\n]*',          # 1. 格式
            r'^[\d一二三四五六七八九十]+、\s*[^\n]*',   # 一、格式
        ]
        
        # 条款模式
        self.article_patterns = [
            r'^第[一二三四五六七八九十\d]+条\s*[^\n]*',
            r'^第[一二三四五六七八九十\d]+条[^\n]*',
            r'^\d+\.\d+\.\d+\s*[^\n]*',
            r'^\d+\.\d+\s*[^\n]*',
        ]
        
        # 子条款模式（这些应该跟随主条款，而不是单独成块）
        self.sub_article_patterns = [
            r'^（[一二三四五六七八九十\d]+）\s*[^\n]*',  # （一）格式
            r'^\([一二三四五六七八九十\d]+\)\s*[^\n]*',  # (一) 格式
            r'^（[①②③④⑤⑥⑦⑧⑨⑩]+\）\s*[^\n]*',      # （①）格式
            r'^\([①②③④⑤⑥⑦⑧⑨⑩]+\)\s*[^\n]*',       # (①) 格式
        ]
        
        # 组合所有模式
        self.all_patterns = self.chapter_patterns + self.sub_article_patterns
        

    
    def chunk_law_document(self, document: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        专门针对法规文档的分块方法
        :param document: 文档对象
        :return: 分块后的文档列表
        """
        text = document['text']
        filename = document.get('filename', 'unknown')
            
        logger.info(f"开始按法规结构分块文档: {filename}")
            
        # 按行分割文本
        lines = text.split('\n')
            
        # 识别章节结构
        sections = self._identify_sections(lines)
            
        # 构建分块
        chunks = []
        current_section_path = []
            
        for section in sections:
            section_type = section['type']
            section_content = section['content']
            section_header = section['header']
                
            # 更新当前章节路径
            if section_type in ['chapter', 'section']:
                # 如果是章节，则更新路径
                if section_type == 'chapter':
                    current_section_path = [section_header]
                elif section_type == 'section':
                    if len(current_section_path) > 0:
                        current_section_path.append(section_header)
                    else:
                        current_section_path = [section_header]
            elif section_type == 'article':
                # 如果是条款，保持当前路径
                pass
            elif section_type == 'sub_article':
                # 子条款不需要更新路径，它属于前一个条款
                continue  # 跳过子条款，因为它们已经被合并到父级条款中
                
            # 跳过子条款的处理，因为它们已经被合并到父级中
            if section_type == 'sub_article':
                continue
                    
            # 将章节标题添加到内容前面
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
                
            # 检查内容长度，如果太长则进一步分块
            if len(full_content) > self.chunk_size:
                sub_chunks = self._split_large_content(full_content, current_section_path)
                chunks.extend(sub_chunks)
            else:
                # 过滤掉只有标题而没有实质内容的块
                # 检查是否只是标题而没有实际内容
                if section_header:
                    # 移除标题部分，得到除标题和章节路径外的内容
                    content_without_header = full_content.replace(section_header, '', 1).strip()
                                    
                    # 如果当前section_path不为空，也从内容中移除章节路径的标题（避免路径信息影响判断）
                    for path_header in current_section_path:
                        content_without_header = content_without_header.replace(path_header, '', 1)
                                                    
                    content_without_header = content_without_header.strip()
                                    
                    # 移除可能的注释（如 # 这个只有标题没有内容）
                    content_without_comments = re.sub(r'#.*$', '', content_without_header, flags=re.MULTILINE).strip()
                                    
                    # 检查除标题外的内容是否为空或只有很少的有效字符
                    # 计算有意义的字符（中文、英文字母、数字、标点符号）
                    meaningful_chars = sum(1 for c in content_without_comments if c.isalnum() or c in '，。！？；：、""\'\'（）【】[]《》〈〉「」『』…—')
                                        
                    # 特殊处理：如果是章节类型（chapter/section）且没有实质性内容，则跳过
                    if section_type in ['chapter', 'section'] and meaningful_chars < 5:
                        logger.debug(f"跳过仅有标题或内容过少的章节: {section_header}")
                        continue
                                        
                    # 对于article类型，如果标题后没有实质内容（如"第七条"后面没有任何内容），也跳过
                    if section_type == 'article':
                        # 检查是否是简单序号标题（如"第X条"）且内容主要是注释
                        is_simple_numbered_article = re.match(r'^第[一二三四五六七八九十\d]+条', section_header.strip())
                        
                        # 检查内容是否主要是注释
                        is_mainly_comment = '#' in section_header and meaningful_chars < 5
                        
                        # 如果是简单的序号条款且主要内容是注释，则跳过
                        if is_simple_numbered_article and is_mainly_comment:
                            logger.debug(f"跳过内容主要是注释的简单条款: {section_header}")
                            continue
                    
                chunk = {
                    'doc_id': document.get('doc_id', ''),
                    'filename': filename,
                    'file_type': document.get('file_type', ''),
                    'doc_type': document.get('doc_type', 'internal_regulation'),  # 添加文档类型
                    'title': document.get('title', ''),  # 添加标题
                    'text': full_content,
                    'semantic_boundary': section_type,
                    'section_path': current_section_path.copy(),
                    'header': section_header,
                    'char_count': len(full_content)
                }
                chunks.append(chunk)
            
        logger.info(f"法规文档分块完成，共生成 {len(chunks)} 个文本块")
        return chunks
    
    def _identify_sections(self, lines: List[str]) -> List[Dict[str, Any]]:
        """
        识别文档中的章节结构
        :param lines: 文档行列表
        :return: 章节列表
        """
        sections = []
        
        for line in lines:
            # 检查是否是章节标题
            section_type, header = self._check_section_header(line)
            
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
                        'content': header + '\n'  # 只包含标题行
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
    
    def _check_section_header(self, line: str) -> tuple:
        """
        检查行是否为章节标题
        :param line: 文本行
        :return: (章节类型, 章节标题) 或 (None, '')
        """
        stripped_line = line.strip()
        
        # 跳过空行
        if not stripped_line:
            return None, ''
        
        # 检查子条款模式（优先检查，因为它们应该跟随父条款）
        for pattern in self.sub_article_patterns:
            match = re.match(pattern, stripped_line)
            if match:
                header = match.group(0)
                return 'sub_article', header
        
        # 检查章节模式
        for pattern in self.chapter_patterns:
            match = re.match(pattern, stripped_line)
            if match:
                header = match.group(0)
                if any(re.match(p, header) for p in self.article_patterns):
                    return 'article', header
                elif '章' in header:
                    return 'chapter', header
                elif '节' in header:
                    return 'section', header
                else:
                    return 'article', header
        
        return None, ''
    
    def _split_large_content(self, content: str, section_path: List[str]) -> List[Dict[str, Any]]:
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