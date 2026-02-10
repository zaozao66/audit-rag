#!/usr/bin/env python3
"""
RAG系统 - 支持独立存储和搜索功能
"""

import logging
import sys
import argparse
import os
from typing import List, Dict, Any
import json

def get_logger():
    """获取日志记录器，根据环境动态配置日志文件路径"""
    import logging
    import os
    
    # 根据环境决定日志文件位置
    env = os.getenv('ENVIRONMENT', 'development')
    if env == 'production':
        log_file = '/data/appLogs/api_server.log'
    else:
        log_file = './logs/api_server.log'

    # 创建日志目录（如果不存在）
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError:
            # 如果生产环境路径不可写，降级到本地路径
            if env == 'production':
                log_file = './logs/api_server.log'
                log_dir = os.path.dirname(log_file)
                if log_dir and not os.path.exists(log_dir):
                    os.makedirs(log_dir, exist_ok=True)

    # 配置日志处理器
    try:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
    except OSError:
        # 如果无法创建日志文件，只使用控制台处理器
        file_handler = None

    console_handler = logging.StreamHandler()

    # 设置日志格式
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    if file_handler:
        file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    # 配置logger
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    if file_handler:
        logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

# 初始化日志记录器
logger = get_logger()

import sys
# 添加src目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.utils.config_loader import load_config
from src.indexing.vector.embedding_providers import TextEmbeddingProvider
from src.retrieval.router.rag_processor import RAGProcessor, process_user_uploaded_documents


def create_embedding_provider(config: dict) -> TextEmbeddingProvider:
    """根据配置创建嵌入提供者"""
    logger.info("创建Text Embedding提供者...")
    
    # 直接使用从配置文件加载的配置
    embedding_config = config['embedding_model']
    
    # 获取环境信息
    env = config.get('environment', 'development')
    logger.info(f"当前运行环境: {env}")
    
    api_key = embedding_config['api_key']
    endpoint = embedding_config['endpoint']
    model_name = embedding_config['model_name']
    ssl_verify = embedding_config.get('ssl_verify', True)
    
    provider = TextEmbeddingProvider(
        api_key=api_key,
        endpoint=endpoint,
        model_name=model_name,
        ssl_verify=ssl_verify,
        env=env
    )
    
    logger.info(f"Text Embedding提供者创建完成，模型: {model_name}, 环境: {env}")
    return provider


def store_documents(args):
    """存储文档功能"""
    logger.info("=== 开始存储文档到向量库 ===")
    
    try:
        # 加载配置
        logger.info("加载配置文件...")
        config = load_config()
        
        # 创建嵌入提供者
        logger.info("创建嵌入提供者...")
        embedding_provider = create_embedding_provider(config)
        
        # 获取配置参数
        chunk_size = config['chunking']['chunk_size']
        overlap = config['chunking']['overlap']
        # 默认分块器类型
        chunker_type = args.chunker_type or config.get('chunking', {}).get('chunker_type', 'smart')
        
        logger.info(f"使用配置参数 - 块大小: {chunk_size}, 重叠: {overlap}, 分块器类型: {chunker_type}")
        
        # 创建RAG处理器，指定向量库存储路径
        vector_store_path = args.store_path or config.get('vector_store_path', './vector_store_text_embedding')
        logger.info(f"使用向量库存储路径: {vector_store_path}")
        
        rag_processor = RAGProcessor(
            embedding_provider=embedding_provider,
            chunk_size=chunk_size,
            overlap=overlap,
            vector_store_path=vector_store_path,
            chunker_type=chunker_type
        )
        
        # 尝试从现有向量库加载（如果存在）
        try:
            rag_processor.load_vector_store(vector_store_path)
            logger.info("成功加载现有向量库，将在此基础上追加新文档")
        except Exception as e:
            logger.info(f"未找到现有向量库，将创建新的向量库: {str(e)}")
        
        # 检查是否有命令行参数传入文档路径
        if args.files:
            file_paths = args.files
            logger.info(f"将处理用户上传的文档: {file_paths}")
            
            # 处理用户上传的文档
            num_processed = process_user_uploaded_documents(file_paths, rag_processor)
            
            if num_processed > 0:
                logger.info(f"成功处理了 {num_processed} 个文本块")
                logger.info(f"向量库已保存到: {vector_store_path}")
            else:
                logger.warning("未能处理任何用户文档")
        else:
            logger.warning("没有提供文档路径，请使用 --files 参数指定要存储的文档")
        
        logger.info("=== 文档存储完成 ===")
        
    except Exception as e:
        logger.error(f"文档存储过程中出错: {e}")
        import traceback
        traceback.print_exc()


def search_documents(args):
    """搜索文档功能"""
    logger.info("=== 开始搜索文档 ===")
    
    try:
        # 加载配置
        logger.info("加载配置文件...")
        config = load_config()
        
        # 创建嵌入提供者
        logger.info("创建嵌入提供者...")
        embedding_provider = create_embedding_provider(config)
        
        # 获取配置参数
        chunk_size = config['chunking']['chunk_size']
        overlap = config['chunking']['overlap']
        top_k = config['search']['top_k']
        logger.info(f"使用配置参数 - 块大小: {chunk_size}, 重叠: {overlap}, top_k: {top_k}")
        
        # 创建RAG处理器，指定向量库存储路径
        vector_store_path = args.store_path or config.get('vector_store_path', './vector_store_text_embedding')
        logger.info(f"使用向量库存储路径: {vector_store_path}")
        
        rag_processor = RAGProcessor(
            embedding_provider=embedding_provider,
            chunk_size=chunk_size,
            overlap=overlap,
            vector_store_path=vector_store_path
        )
        
        # 加载向量库
        logger.info("加载向量库...")
        rag_processor.load_vector_store(vector_store_path)
        
        # 执行搜索
        query = args.query
        if query:
            results = rag_processor.search(query, top_k=top_k)
            
            print(f"\n查询: {query}")
            print("搜索结果:")
            for i, result in enumerate(results, 1):
                print(f"{i}. 相似度分数: {result['score']:.4f}")
                print(f"   文本: {result['document']['text']}")
                print()
        else:
            # 交互式搜索模式
            while True:
                query = input("\n请输入您的查询 (输入 'quit' 或 'exit' 退出): ").strip()
                if query.lower() in ['quit', 'exit']:
                    break
                if query:
                    try:
                        results = rag_processor.search(query, top_k=top_k)
                        
                        print(f"\n查询: {query}")
                        print("搜索结果:")
                        for i, result in enumerate(results, 1):
                            print(f"{i}. 相似度分数: {result['score']:.4f}")
                            print(f"   文本: {result['document']['text']}")
                            print()
                    except Exception as e:
                        logger.error(f"搜索过程中出错: {e}")
        
        logger.info("=== 文档搜索完成 ===")
        
    except Exception as e:
        logger.error(f"文档搜索过程中出错: {e}")
        import traceback
        traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(description='RAG系统 - 支持独立存储和搜索功能')
    subparsers = parser.add_subparsers(dest='command', help='可用的命令')
    
    # 存储命令
    store_parser = subparsers.add_parser('store', help='存储文档到向量库')
    store_parser.add_argument('--files', nargs='+', help='要存储的文档文件路径')
    store_parser.add_argument('--store-path', help='向量库存储路径，默认为 ./vector_store_text_embedding')
    store_parser.add_argument('--chunker-type', choices=['default', 'regulation', 'audit_report', 'smart'], default='smart',
                             help='分块器类型：default (默认), regulation (制度文件), audit_report (审计报告), smart (智能识别)')
    
    # 搜索命令
    search_parser = subparsers.add_parser('search', help='从向量库搜索文档')
    search_parser.add_argument('--query', help='要搜索的查询文本，如果不提供则进入交互模式')
    search_parser.add_argument('--store-path', help='向量库路径，默认为 ./vector_store_text_embedding')
    
    # 清空向量库命令
    clear_parser = subparsers.add_parser('clear', help='清空向量库')
    clear_parser.add_argument('--store-path', help='向量库路径，默认为 ./vector_store_text_embedding')
    
    args = parser.parse_args()
    
    if args.command == 'store':
        store_documents(args)
    elif args.command == 'search':
        search_documents(args)
    elif args.command == 'clear':
        logger.info("=== 清空向量库 ===")
        
        # 加载配置
        config = load_config()
        
        # 创建嵌入提供者（虽然不需要，但为了创建RAGProcessor实例）
        embedding_provider = create_embedding_provider(config)
        
        # 获取配置参数
        chunk_size = config['chunking']['chunk_size']
        overlap = config['chunking']['overlap']
        
        # 创建RAG处理器
        vector_store_path = args.store_path or config.get('vector_store_path', './vector_store_text_embedding')
        
        rag_processor = RAGProcessor(
            embedding_provider=embedding_provider,
            chunk_size=chunk_size,
            overlap=overlap,
            vector_store_path=vector_store_path
        )
        
        # 清空向量库
        rag_processor.clear_vector_store()
        
        # 保存清空的向量库
        try:
            rag_processor.save_vector_store()
        except ValueError as ve:
            if "没有可保存的向量库" in str(ve):
                # 如果向量库未初始化，创建一个新的空向量库并保存
                from src.indexing.vector.vector_store import VectorStore
                rag_processor.vector_store = VectorStore(dimension=rag_processor.dimension or 1024)
                rag_processor.save_vector_store()
            else:
                raise  # 重新抛出其他ValueError异常
        
        logger.info(f"向量库已清空并保存: {vector_store_path}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()