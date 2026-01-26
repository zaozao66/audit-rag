import os
import logging
from typing import Dict, Any, List
from docx import Document
import pdfplumber
import chardet


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
    def load_document(file_path: str) -> str:
        """
        根据文件类型加载文档内容
        :param file_path: 文件路径
        :return: 文档文本内容
        """
        file_type = DocumentProcessor.detect_file_type(file_path)
        logger.info(f"检测到文件类型: {file_type}，文件路径: {file_path}")
        
        if file_type == 'pdf':
            return DocumentProcessor._load_pdf(file_path)
        elif file_type == 'docx':
            return DocumentProcessor._load_docx(file_path)
        elif file_type == 'txt':
            return DocumentProcessor._load_txt(file_path)
        else:
            raise ValueError(f"不支持的文件类型: {file_type}")
    
    @staticmethod
    def _load_pdf(file_path: str) -> str:
        """
        加载PDF文档
        :param file_path: PDF文件路径
        :return: 文档文本内容
        """
        logger.info(f"开始加载PDF文档: {file_path}")
        text_parts = []
        
        try:
            with pdfplumber.open(file_path) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
                    logger.debug(f"处理PDF第 {page_num + 1} 页，提取文本长度: {len(page_text) if page_text else 0}")
            
            full_text = "\n".join(text_parts)
            logger.info(f"PDF文档加载完成，总文本长度: {len(full_text)}")
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


def process_uploaded_documents(file_paths: List[str]) -> List[Dict[str, Any]]:
    """
    处理用户上传的多个文档
    :param file_paths: 文件路径列表
    :return: 文档列表，每个元素包含文档内容和元数据
    """
    logger.info(f"开始处理 {len(file_paths)} 个上传的文档")
    
    documents = []
    
    for idx, file_path in enumerate(file_paths):
        logger.info(f"正在处理文档 {idx + 1}/{len(file_paths)}: {file_path}")
        
        try:
            # 获取文件名（不含路径）
            filename = os.path.basename(file_path)
            
            # 加载文档内容
            content = DocumentProcessor.load_document(file_path)
            
            # 创建文档对象
            doc_obj = {
                'doc_id': f'doc_{idx}',
                'filename': filename,
                'file_path': file_path,
                'file_type': DocumentProcessor.detect_file_type(file_path),
                'text': content,
                'char_count': len(content)
            }
            
            documents.append(doc_obj)
            logger.info(f"文档 {filename} 处理完成，字符数: {len(content)}")
            
        except Exception as e:
            logger.error(f"处理文档 {file_path} 时发生错误: {e}")
            continue  # 继续处理其他文档
    
    logger.info(f"所有文档处理完成，成功处理 {len(documents)} 个文档")
    return documents


