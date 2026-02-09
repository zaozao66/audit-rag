import re
import logging
from typing import List, Dict, Any
from document_chunker import DocumentChunker

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class AuditReportChunker(DocumentChunker):
    """
    审计报告文档分块器
    按照审计报告的层级结构进行智能分块，保持内容的完整性和逻辑连贯性
    """
    
    def __init__(self, chunk_size: int = 1024, overlap: int = 50):
        super().__init__(chunk_size=chunk_size, overlap=overlap)
        
        # 审计报告常见的层级模式
        # 一级标题：一、二、三、...
        self.level1_patterns = [
            r'^[一二三四五六七八九十]+、\s*[^\n]*',  # 一、审计概况
        ]
        
        # 二级标题：（一）（二）（三）... 或 (一)(二)(三)...
        self.level2_patterns = [
            r'^（[一二三四五六七八九十]+）\s*[^\n]*',  # （一）审计目的
            r'^\([一二三四五六七八九十]+\)\s*[^\n]*',  # (一) 审计目的
        ]
        
        # 三级标题/列表项：1. 2. 3. ...
        self.level3_patterns = [
            r'^\d+\.\s*[^\n]*',  # 1. 采购计划编制...
            r'^\d+\.(?!\d)',
        ]
        
        # 要点/条款模式
        self.item_patterns = [
            r'^[①②③④⑤⑥⑦⑧⑨⑩]+[、\s]*[^\n]*',  # ①②③...
            r'^[\d]+）\s*[^\n]*',  # 1）2）3）...
        ]
        
        # 审计报告特征关键词（用于识别是否为审计报告）
        self.audit_keywords = [
            '审计', '审计报告', '审计署', '审计发现', '审计内容', '审计目的',
            '审计范围', '审计方法', '审计结果', '审计意见', '审计建议',
            '问题', '整改', '合规', '违规', '存在问题', '发现问题',
            '被审计单位', '审计期间', '审计工作', '审计事项'
        ]
    
    def chunk_audit_report(self, document: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        专门针对审计报告的分块方法：基于层级的智能聚合策略
        1. 一级和二级标题强制换块，保持大结构的独立性
        2. 三级及以下要点优先合并，直到达到 chunk_size，防止内容过碎
        """
        text = document['text']
        filename = document.get('filename', 'unknown')
        
        logger.info(f"开始按审计报告结构（智能聚合模式）分块文档: {filename}")
        
        # 按行分割文本
        lines = text.split('\n')
        
        # 识别章节结构
        sections = self._identify_sections(lines)
        
        chunks = []
        current_level1_title = ""
        current_level2_title = ""
        
        # 用于聚合内容的缓冲区
        buffer_content = ""
        buffer_sections = [] # 记录当前块包含的所有小标题
        buffer_type = ""     # 当前块的主体类型
        
        def flush_buffer():
            nonlocal buffer_content, buffer_sections, buffer_type
            if not buffer_content.strip():
                return
                    
            # 过滤掉只有标题没有实质内容的块
            # 1. 移除一级和二级标题（不移除 level3 标题，因为它们是内容的一部分）
            content_to_check = buffer_content
            for t in [current_level1_title, current_level2_title]:
                if t:
                    content_to_check = content_to_check.replace(t, "", 1)
                    
            # 2. 移除空白字符后检查剩余内容
            content_to_check = content_to_check.strip()
                    
            # 3. 计算有意义的字符数（排除空白、换行、标点符号）
            meaningful_chars = len([c for c in content_to_check if c.strip() and c not in '\n\r\t、，。：；'])
                    
            # 4. 检查关键信息（但只在剩余内容中检查，不在标题中检查）
            has_key_info = any(k in content_to_check for k in ['亿元', '万元', '违规', '问题'])
                    
            # 5. 过滤逻辑
            # 如果是一级或二级标题且没有实质内容，则跳过
            # 对于纯标题块，即使标题中包含关键词（如"审计"、"整改"），也应该跳过
            if buffer_type in ['level1', 'level2']:
                if meaningful_chars < 10 and not has_key_info:
                    logger.debug(f"跳过纯标题块: {buffer_sections[0] if buffer_sections else 'unknown'} (实质字符: {meaningful_chars})")
                    buffer_content = ""
                    buffer_sections = []
                    return
            # 其他类型（level3/item/content）的要求更宽松
            elif meaningful_chars < 5 and not has_key_info:
                logger.debug(f"跳过过短块: type={buffer_type} (实质字符: {meaningful_chars})")
                buffer_content = ""
                buffer_sections = []
                return
                    
            # 如果块中只有文档标题（content 类型）且内容过短，也跳过
            if buffer_type == 'content' and len(buffer_content.strip()) < 20:
                logger.debug(f"跳过过短的文档标题块: {buffer_content.strip()[:30]}")
                buffer_content = ""
                buffer_sections = []
                return

            # 构建块对象
            chunk = {
                'doc_id': document.get('doc_id', ''),
                'filename': filename,
                'file_type': document.get('file_type', ''),
                'doc_type': document.get('doc_type', 'external_report'),
                'title': document.get('title', ''),
                'text': buffer_content.strip(),
                'semantic_boundary': buffer_type,
                'level1_title': current_level1_title,
                'level2_title': current_level2_title,
                'section_header': buffer_sections[0] if buffer_sections else "",
                'all_headers': buffer_sections,
                'char_count': len(buffer_content.strip())
            }
            chunks.append(chunk)
            # 重置缓冲区
            buffer_content = ""
            buffer_sections = []

        for section in sections:
            section_type = section['type']
            section_content = section['content'].strip()
            section_header = section['header'].strip()
            
            # 1. 遇到一级或二级标题，必须刷新缓冲区（强制切分大章节）
            if section_type in ['level1', 'level2']:
                flush_buffer()
                
                # 更新层级路径
                if section_type == 'level1':
                    current_level1_title = section_header
                    current_level2_title = ""
                    # 一级标题开始新块
                    buffer_content = section_content
                else:
                    current_level2_title = section_header
                    # 二级标题开始新块，注入一级标题作为上下文
                    context = []
                    if current_level1_title:
                        context.append(current_level1_title)
                    context.append(section_content)
                    buffer_content = "\n".join(context)
                
                buffer_sections = [section_header] if section_header else []
                buffer_type = section_type
                
            # 2. 遇到三级要点或普通内容，尝试聚合
            else:
                # 构建带有上下文路径的完整内容（仅当缓冲区为空时添加路径）
                if not buffer_content:
                    context = []
                    if current_level1_title: context.append(current_level1_title)
                    if current_level2_title: context.append(current_level2_title)
                    if context:
                        buffer_content = "\n".join(context) + "\n"
                    buffer_type = section_type
                
                # 检查加入当前节后是否超过限制
                potential_content = buffer_content + "\n" + section_content
                
                if len(potential_content) > self.chunk_size and buffer_content.strip():
                    # 超过限制，先发出当前块
                    flush_buffer()
                    
                    # 重新开始新块，并注入上下文
                    context = []
                    if current_level1_title: context.append(current_level1_title)
                    if current_level2_title: context.append(current_level2_title)
                    buffer_content = "\n".join(context) + "\n" + section_content
                    buffer_sections = [section_header] if section_header else []
                    buffer_type = section_type + "_cont"
                else:
                    # 未超过限制，聚合进去
                    if buffer_content and not buffer_content.endswith("\n"):
                        buffer_content += "\n"
                    buffer_content += section_content
                    if section_header:
                        buffer_sections.append(section_header)

        # 处理最后一个缓冲区
        flush_buffer()
        
        logger.info(f"审计报告分块完成（智能聚合模式），共生成 {len(chunks)} 个文本块")
        return chunks
    
    def _identify_sections(self, lines: List[str]) -> List[Dict[str, Any]]:
        """
        识别文档中的章节结构
        :param lines: 文档行列表
        :return: 章节列表
        """
        sections = []
        
        for line in lines:
            stripped_line = line.strip()
            
            # 跳过空行
            if not stripped_line:
                if sections:
                    sections[-1]['content'] += '\n'
                continue
            
            # 检查是否是章节标题（按优先级检查）
            section_type, header = self._check_section_header(stripped_line)
            
            if section_type:
                # 创建新的章节
                sections.append({
                    'type': section_type,
                    'header': header.strip(),
                    'content': header + '\n'
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
        
        # 按优先级检查各级标题
        # 1. 检查一级标题
        for pattern in self.level1_patterns:
            match = re.match(pattern, stripped_line)
            if match:
                return 'level1', stripped_line
        
        # 2. 检查二级标题
        for pattern in self.level2_patterns:
            match = re.match(pattern, stripped_line)
            if match:
                return 'level2', stripped_line
        
        # 3. 检查三级标题（如 1. 2. 3.）
        for pattern in self.level3_patterns:
            match = re.match(pattern, stripped_line)
            if match:
                return 'level3', stripped_line
        
        # 4. 检查要点模式（如 ① ② 或 1） 2））
        for pattern in self.item_patterns:
            match = re.match(pattern, stripped_line)
            if match:
                return 'item', stripped_line
        
        return None, ''
    
    def _split_large_content(
        self, 
        content: str, 
        document: Dict[str, Any],
        section_type: str,
        level1_title: str,
        level2_title: str,
        section_header: str
    ) -> List[Dict[str, Any]]:
        """
        将大块内容进一步分割，同时保持上下文信息
        :param content: 大块内容
        :param document: 文档对象
        :param section_type: 章节类型
        :param level1_title: 一级标题
        :param level2_title: 二级标题
        :param section_header: 当前节标题
        :return: 分割后的小块列表
        """
        chunks = []
        
        # 按段落分割
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
        
        if not paragraphs:
            # 如果没有明显段落分割，按固定大小分割
            paragraphs = [p.strip() for p in content.split('\n') if p.strip()]
        
        if not paragraphs:
            return []
        
        # 构建标题上下文
        title_context = []
        if level1_title:
            title_context.append(level1_title)
        if level2_title:
            title_context.append(level2_title)
        if section_header and section_header not in title_context:
            title_context.append(section_header)
        
        title_part = '\n'.join(title_context) + '\n\n' if title_context else ''
        
        current_chunk = title_part
        current_size = len(current_chunk)
        
        for paragraph in paragraphs:
            # 跳过标题行（避免重复）
            if paragraph in title_context:
                continue
            
            paragraph_with_separator = paragraph + '\n\n'
            paragraph_size = len(paragraph_with_separator)
            
            if current_size + paragraph_size > self.chunk_size and current_chunk.strip() != title_part.strip():
                # 保存当前块
                chunk = {
                    'doc_id': document.get('doc_id', ''),
                    'filename': document.get('filename', 'audit_report'),
                    'file_type': document.get('file_type', 'txt'),
                    'doc_type': document.get('doc_type', 'external_report'),
                    'title': document.get('title', ''),
                    'text': current_chunk.strip(),
                    'semantic_boundary': f'{section_type}_part',
                    'level1_title': level1_title,
                    'level2_title': level2_title,
                    'section_header': section_header,
                    'char_count': len(current_chunk)
                }
                chunks.append(chunk)
                
                # 开始新块，包含标题上下文
                current_chunk = title_part + paragraph_with_separator
                current_size = len(title_part) + paragraph_size
            else:
                current_chunk += paragraph_with_separator
                current_size += paragraph_size
        
        # 添加最后一块
        if current_chunk.strip() and len(current_chunk.strip()) > len(title_part.strip()):
            chunk = {
                'doc_id': document.get('doc_id', ''),
                'filename': document.get('filename', 'audit_report'),
                'file_type': document.get('file_type', 'txt'),
                'doc_type': document.get('doc_type', 'external_report'),
                'title': document.get('title', ''),
                'text': current_chunk.strip(),
                'semantic_boundary': f'{section_type}_part',
                'level1_title': level1_title,
                'level2_title': level2_title,
                'section_header': section_header,
                'char_count': len(current_chunk)
            }
            chunks.append(chunk)
        
        return chunks
    
    def chunk_documents(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        重写父类方法，对审计报告使用专门的分块逻辑
        """
        all_chunks = []
        
        for doc in documents:
            # 如果显式指定了使用审计报告分块器，或者自动检测是审计报告，则使用专门逻辑
            if self.__class__ == AuditReportChunker or self._is_audit_report(doc):
                logger.info(f"使用审计报告分块逻辑处理: {doc.get('filename', 'unknown')}")
                chunks = self.chunk_audit_report(doc)
            else:
                # 对非审计报告使用普通分块方法
                logger.info(f"使用普通分块器: {doc.get('filename', 'unknown')}")
                chunks = super().chunk_documents([doc])
            
            all_chunks.extend(chunks)
        
        return all_chunks
    
    def _is_audit_report(self, document: Dict[str, Any]) -> bool:
        """
        判断是否为审计报告
        :param document: 文档对象
        :return: 是否为审计报告
        """
        text = document.get('text', '')
        filename = document.get('filename', '')
        doc_type = document.get('doc_type', '')
        
        # 1. 根据文档类型判断
        if doc_type in ['internal_report', 'external_report']:
            return True
        
        # 2. 检查文件名
        audit_filename_keywords = ['审计报告', '审计', 'audit', 'report']
        for keyword in audit_filename_keywords:
            if keyword in filename.lower():
                return True
        
        # 3. 检查内容关键词（前1000个字符）
        text_sample = text[:1000]
        keyword_count = sum(1 for keyword in self.audit_keywords if keyword in text_sample)
        
        # 如果包含3个以上审计关键词，认为是审计报告
        if keyword_count >= 3:
            return True
        
        # 4. 检查是否包含审计报告的典型结构
        structure_indicators = [
            r'[一二三四五六七八九十]+、\s*审计',
            r'（[一二三四五六七八九十]+）\s*审计',
            r'审计概况',
            r'审计发现',
            r'审计意见',
            r'审计建议',
            r'被审计单位'
        ]
        
        for pattern in structure_indicators:
            if re.search(pattern, text_sample):
                return True
        
        return False
