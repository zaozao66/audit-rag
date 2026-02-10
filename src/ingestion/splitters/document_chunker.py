import re
import logging
from typing import List, Dict, Any

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class DocumentChunker:
    """制度文档分块器 - 按语义边界分割文档以保持上下文完整性"""
    
    def __init__(self, chunk_size: int = 512, overlap: int = 50):
        """
        初始化文档分块器
        :param chunk_size: 每个块的最大字符数
        :param overlap: 相邻块之间的重叠字符数（保持上下文连续性）
        """
        self.chunk_size = chunk_size
        self.overlap = overlap
        logger.info(f"制度文档分块器初始化完成，块大小: {chunk_size}, 重叠: {overlap}")
    
    def chunk_text(self, text: str) -> List[Dict[str, Any]]:
        """
        将单个文本分割成块，优先按语义边界分割
        :param text: 输入的长文本
        :return: 分块后的文本列表，每个元素包含文本内容和元数据
        """
        # 如果文本长度小于等于块大小，直接返回整个文本作为一个块
        if len(text) <= self.chunk_size:
            return [{
                'text': text,
                'start_pos': 0,
                'end_pos': len(text),
                'chunk_id': 'chunk_0',
                'semantic_boundary': 'full_text'
            }]

        # 首先尝试按语义边界分割
        semantic_chunks = self._split_by_semantic_boundaries(text)
        
        # 如果语义分割的块仍然太长，则进一步分割
        final_chunks = []
        chunk_count = 0
        for semantic_chunk in semantic_chunks:
            if len(semantic_chunk) <= self.chunk_size:
                # 语义块长度合适，直接使用
                final_chunks.append({
                    'text': semantic_chunk,
                    'start_pos': 0,
                    'end_pos': len(semantic_chunk),
                    'chunk_id': f'chunk_{chunk_count}',
                    'semantic_boundary': 'semantic_section'
                })
                chunk_count += 1
            else:
                # 语义块太长，按固定长度分割
                sub_chunks = self._split_by_fixed_length(semantic_chunk)
                for sub_chunk in sub_chunks:
                    final_chunks.append({
                        'text': sub_chunk,
                        'start_pos': 0,
                        'end_pos': len(sub_chunk),
                        'chunk_id': f'chunk_{chunk_count}',
                        'semantic_boundary': 'fixed_length_split'
                    })
                    chunk_count += 1
        
        return final_chunks
    
    def _split_by_semantic_boundaries(self, text: str) -> List[str]:
        """
        按语义边界分割文本，如标题、条款、段落等
        :param text: 输入文本
        :return: 按语义边界分割的文本列表
        """
        # 定义语义分割的正则表达式模式
        # 匹配标题和条款，如 "第一条"、"第一章"、"第一节" 等
        patterns = [
            r'第[一二三四五六七八九十\d]+[条章节][^第\n]*(?=第[一二三四五六七八九十\d]+[条章节]|$)',  # 条、章、节
            r'[一二三四五六七八九十\d]+[、．.]?\s*[^一二三四五六七八九十\d\n]*(?=[一二三四五六七八九十\d]+[、．.]?\s*|$)',  # 数字编号
            r'\d+\.[^一二三四五六七八九十\d\n]*(?=\d+\.|$)',  # 点号编号
            r'[（\(][一二三四五六七八九十][）\)]\s*[^（\(]*(?=[（\(][一二三四五六七八九十][）\)]|$)',  # 中文括号编号
        ]
        
        # 优先使用更精确的分割模式
        for pattern in patterns[:3]:  # 只使用前三组最常用的模式
            matches = re.findall(pattern, text)
            matches = [match.strip() for match in matches if match.strip()]
            if len(matches) > 1:
                return matches
        
        # 如果没有找到语义边界，则按段落分割
        paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
        if len(paragraphs) > 1:
            return paragraphs
        
        # 如果没有段落分割，则使用固定长度分割
        return [text]
    
    def _split_by_fixed_length(self, text: str) -> List[str]:
        """
        按固定长度分割文本，尽量在句子或词语边界分割
        :param text: 输入文本
        :return: 固定长度分割的文本列表
        """
        chunks = []
        start = 0
        
        while start < len(text):
            end = start + self.chunk_size
            
            # 如果超出文本长度，调整为文本结尾
            if end >= len(text):
                chunks.append(text[start:])
                break
            
            # 尝试在句子边界分割（句号、分号、冒号、感叹号、问号）
            sentence_end = -1
            for punct in ['。', '；', '：', '！', '？', '\n']:
                pos = text.rfind(punct, start, end)
                if pos > sentence_end and pos > start + self.chunk_size // 2:  # 确保不会产生太短的块
                    sentence_end = pos + 1  # 包含标点符号
            
            if sentence_end != -1:
                # 在句子边界分割
                chunk = text[start:sentence_end].strip()
                if chunk:
                    chunks.append(chunk)
                start = sentence_end
            else:
                # 在词语边界分割（逗号、顿号等）
                word_end = -1
                for punct in ['，', '、', ' ', '\t']:
                    pos = text.rfind(punct, start, end)
                    if pos > word_end and pos > start + self.chunk_size // 2:
                        word_end = pos + 1  # 包含标点符号
                
                if word_end != -1:
                    # 在词语边界分割
                    chunk = text[start:word_end].strip()
                    if chunk:
                        chunks.append(chunk)
                    start = word_end
                else:
                    # 无法找到合适的分割点，强制按长度分割
                    chunk = text[start:end].strip()
                    if chunk:
                        chunks.append(chunk)
                    start = end
            
            # 避免无限循环
            if start == 0:  # 如果无法分割第一个块，强制分割
                chunks.append(text[:end])
                start = end
        
        return chunks
    
    def chunk_documents(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        分割多个文档
        :param documents: 文档列表
        :return: 分块后的文档列表
        """
        all_chunks = []
        
        for doc_idx, document in enumerate(documents):
            text = document.get('text', '')
            metadata = {k: v for k, v in document.items() if k != 'text'}
            
            # 分割单个文档
            chunks = self.chunk_text(text)
            
            # 合并文档元数据和块元数据
            for chunk_idx, chunk in enumerate(chunks):
                chunk_data = {
                    'text': chunk['text'],
                    'doc_id': document.get('doc_id', f'doc_{doc_idx}'),
                    'chunk_id': f"{document.get('doc_id', f'doc_{doc_idx}')}_chunk_{chunk_idx}",
                    'start_pos': chunk.get('start_pos', 0),
                    'end_pos': chunk.get('end_pos', len(chunk['text'])),
                    'semantic_boundary': chunk.get('semantic_boundary', 'unknown'),
                    'doc_type': document.get('doc_type', 'internal_regulation'),  # 确保文档类型传递
                    'title': document.get('title', ''),  # 确保标题传递
                    **metadata  # 合并原始文档的元数据
                }
                all_chunks.append(chunk_data)
        
        return all_chunks