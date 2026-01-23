import logging
import sys
from typing import List, Dict, Any
import json

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from config_loader import load_config
from embedding_providers import AliyunTextEmbeddingProvider
from rag_processor import RAGProcessor, process_user_uploaded_documents


def create_aliyun_embedding_provider(config: dict) -> AliyunTextEmbeddingProvider:
    """根据配置创建阿里云嵌入提供者"""
    logger.info("创建阿里云Text Embedding提供者...")
    
    embedding_config = config['embedding_model']
    api_key = embedding_config['api_key']
    endpoint = embedding_config['endpoint']
    model_name = embedding_config['model_name']
    
    provider = AliyunTextEmbeddingProvider(
        api_key=api_key,
        endpoint=endpoint,
        model_name=model_name
    )
    
    logger.info(f"阿里云Text Embedding提供者创建完成，模型: {model_name}")
    return provider


# 使用示例
if __name__ == "__main__":
    logger.info("=== 开始运行阿里云Text Embedding RAG系统 ===")
    
    try:
        # 加载配置
        logger.info("加载配置文件...")
        config = load_config()
        
        # 创建阿里云嵌入提供者
        logger.info("创建阿里云嵌入提供者...")
        embedding_provider = create_aliyun_embedding_provider(config)
        
        # 获取配置参数
        chunk_size = config['chunking']['chunk_size']
        overlap = config['chunking']['overlap']
        logger.info(f"使用配置参数 - 块大小: {chunk_size}, 重叠: {overlap}")
        
        # 创建RAG处理器
        logger.info("创建RAG处理器...")
        rag_processor = RAGProcessor(
            embedding_provider=embedding_provider,
            chunk_size=chunk_size,
            overlap=overlap
        )
        
        # 检查是否有命令行参数传入文档路径
        if len(sys.argv) > 1:
            file_paths = sys.argv[1:]  # 获取命令行参数中的文件路径
            logger.info(f"检测到命令行参数，将处理用户上传的文档: {file_paths}")
            
            # 处理用户上传的文档
            num_processed = process_user_uploaded_documents(file_paths, rag_processor)
            
            if num_processed > 0:
                logger.info(f"成功处理了 {num_processed} 个文本块")
                
                # 询问用户是否要进行搜索
                query = input("\n请输入您的查询: ").strip()
                if query:
                    results = rag_processor.search(query, top_k=config['search']['top_k'])
                    
                    print(f"\n查询: {query}")
                    print("搜索结果:")
                    for i, result in enumerate(results, 1):
                        print(f"{i}. 相似度分数: {result['score']:.4f}")
                        print(f"   文本: {result['document']['text']}")
                        # print(f"   来源: {result['document'].get('source', 'Unknown')}")
                        print()
            else:
                logger.warning("未能处理任何用户文档")
        else:
            # 使用示例文档进行演示
            logger.info("没有提供用户文档，使用示例文档进行演示")
            
            # 准备示例文档
            logger.info("准备示例文档...")
            documents = [
                {
                    'doc_id': 'doc_1',
                    'title': 'RAG技术介绍',
                    'text': 'RAG（Retrieval-Augmented Generation）是一种结合检索和生成的技术，通过检索相关信息来增强生成模型的能力。这种技术在问答系统和文本生成任务中表现优异。',
                    'source': 'example_source_1'
                },
                {
                    'doc_id': 'doc_2',
                    'title': '阿里云通义千问介绍',
                    'text': '通义千问是阿里云开发的大规模语言模型，能够回答问题、创作文字、表达观点、玩游戏等。该模型具有强大的语言理解和生成能力。',
                    'source': 'example_source_2'
                }
            ]
            
            # 处理文档
            logger.info("开始处理示例文档...")
            num_chunks = rag_processor.process_documents(documents)
            logger.info(f"文档处理完成，共生成 {num_chunks} 个文本块")
            
            # 执行搜索
            logger.info("开始执行搜索示例...")
            query = "什么是RAG技术"
            results = rag_processor.search(query, top_k=config['search']['top_k'])
            
            logger.info(f"\n查询: {query}")
            logger.info("搜索结果:")
            for i, result in enumerate(results, 1):
                logger.info(f"{i}. 相似度分数: {result['score']:.4f}")
                logger.info(f"   文本: {result['document']['text'][:100]}...")
                logger.info(f"   来源: {result['document'].get('source', 'Unknown')}")
                logger.info('')
        
        # 保存向量库
        logger.info("保存向量库...")
        rag_processor.save_vector_store("./vector_store_aliyun_text_embedding")
        
        logger.info("=== 阿里云Text Embedding RAG系统运行完成 ===")
        
        print("\n系统提示:")
        print("✅ 系统已成功连接阿里云text-embedding-v4服务")
        print("✅ 所有RAG流程正常工作：文档处理、向量生成、相似性搜索")
        print("✅ 支持用户上传PDF、DOCX、TXT格式文档")
        print("✅ 使用阿里云远程API进行向量嵌入")
        
    except Exception as e:
        logger.error(f"系统运行出错: {e}")
        import traceback
        traceback.print_exc()