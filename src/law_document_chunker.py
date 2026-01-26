import re
import logging
from typing import List, Dict, Any
from .document_chunker import DocumentChunker

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
            r'^（[一二三四五六七八九十\d]+）\s*[^\n]*',  # （一）格式
            r'^\([一二三四五六七八九十\d]+\)\s*[^\n]*',  # (一) 格式
            r'^[\d一二三四五六七八九十]+、\s*[^\n]*',   # 一、格式
        ]
        
        # 条款模式
        self.article_patterns = [
            r'^第[一二三四五六七八九十\d]+条\s*[^\n]*',
            r'^第[一二三四五六七八九十\d]+条[^\n]*',
            r'^\d+\.\d+\.\d+\s*[^\n]*',
            r'^\d+\.\d+\s*[^\n]*',
        ]
        
        # 组合所有模式
        self.all_patterns = self.chapter_patterns
    
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
            
            # 将章节标题添加到内容前面
            section_title = ' '.join(current_section_path)
            if section_header and section_header != section_title:
                full_content = f"{section_title}\n{section_header}\n{section_content}"
            elif section_title:
                full_content = f"{section_title}\n{section_content}"
            else:
                full_content = section_content
            
            # 检查内容长度，如果太长则进一步分块
            if len(full_content) > self.chunk_size:
                sub_chunks = self._split_large_content(full_content, current_section_path)
                chunks.extend(sub_chunks)
            else:
                chunk = {
                    'doc_id': document.get('doc_id', ''),
                    'filename': filename,
                    'file_type': document.get('file_type', ''),
                    'text': full_content.strip(),
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
        current_section = {
            'type': 'content',
            'header': '',
            'content': ''
        }
        
        for line in lines:
            # 检查是否是章节标题
            section_type, header = self._check_section_header(line)
            
            if section_type:
                # 如果当前有累积的内容，先保存
                if current_section['content'].strip():
                    sections.append(current_section.copy())
                
                # 开始新的章节
                current_section = {
                    'type': section_type,
                    'header': header.strip(),
                    'content': header + '\n'
                }
            else:
                # 添加内容到当前章节
                current_section['content'] += line + '\n'
        
        # 添加最后一个章节
        if current_section['content'].strip():
            sections.append(current_section)
        
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
        
        # 按段落分割
        paragraphs = content.split('\n\n')
        
        current_chunk = ""
        current_size = 0
        
        for paragraph in paragraphs:
            paragraph_size = len(paragraph)
            
            if current_size + paragraph_size > self.chunk_size and current_chunk:
                # 保存当前块
                chunk = {
                    'doc_id': '',
                    'filename': 'law_document',
                    'file_type': 'txt',
                    'text': current_chunk.strip(),
                    'semantic_boundary': 'sub_article',
                    'section_path': section_path.copy(),
                    'header': section_path[-1] if section_path else '',
                    'char_count': len(current_chunk)
                }
                chunks.append(chunk)
                
                # 开始新块
                current_chunk = paragraph + '\n\n'
                current_size = paragraph_size + 2
            else:
                current_chunk += paragraph + '\n\n'
                current_size += paragraph_size + 2
        
        # 添加最后一块
        if current_chunk.strip():
            chunk = {
                'doc_id': '',
                'filename': 'law_document',
                'file_type': 'txt',
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
            # 检查是否为法规类文档
            if self._is_law_document(doc):
                logger.info(f"检测到法规文档，使用法规分块器: {doc.get('filename', 'unknown')}")
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