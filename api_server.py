"""
RAG系统 - HTTP API接口
支持通过HTTP请求进行文档存储、搜索和清除操作
"""

import logging
import json
from typing import Dict, Any, List
from flask import Flask, request, jsonify, Response
from werkzeug.utils import secure_filename
import sys
import os

# 添加src目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from config_loader import load_config
from src.embedding_providers import TextEmbeddingProvider
from src.rag_processor import RAGProcessor, process_user_uploaded_documents
from src.document_chunker import DocumentChunker
from src.law_document_chunker import LawDocumentChunker
from src.rerank_provider import AliyunRerankProvider, MockRerankProvider

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 创建Flask应用
app = Flask(__name__)

# 全局变量存储RAG处理器实例
rag_processor = None


def initialize_rag_processor(use_law_chunker: bool = False, use_rerank: bool = False):
    """初始化RAG处理器"""
    global rag_processor
    
    # 如果指定了使用法规分块器，且当前处理器不是法规分块器，则重新初始化
    # 或者如果重排序设置发生变化
    if rag_processor is not None and (rag_processor.use_law_chunker != use_law_chunker or 
                                      (rag_processor.rerank_provider is not None) != use_rerank):
        rag_processor = None
    
    if rag_processor is None:
        try:
            # 加载配置
            logger.info("加载配置文件...")
            config = load_config()
            
            # 创建嵌入提供者
            logger.info("创建嵌入提供者...")
            embedding_config = config['embedding_model']
            api_key = embedding_config['api_key']
            endpoint = embedding_config['endpoint']
            model_name = embedding_config['model_name']
            
            embedding_provider = TextEmbeddingProvider(
                api_key=api_key,
                endpoint=endpoint,
                model_name=model_name
            )
            
            # 创建重排序提供者
            rerank_provider = None
            if use_rerank:
                logger.info("创建重排序提供者...")
                try:
                    # 从配置中获取重排序API配置
                    rerank_config = config.get('rerank_model', {})
                    if 'api_key' in rerank_config and rerank_config['api_key']:
                        rerank_provider = AliyunRerankProvider(
                            api_key=rerank_config['api_key'],
                            model_name=rerank_config.get('model_name', 'gte-rerank'),
                            endpoint=rerank_config.get('endpoint', 'https://dashscope.aliyuncs.com/api/v1/services/rerank/text-retrieve-rerank')
                        )
                    else:
                        logger.warning("重排序API密钥未配置，使用模拟重排序提供者")
                        rerank_provider = MockRerankProvider()
                except Exception as e:
                    logger.error(f"创建重排序提供者失败: {e}，使用模拟重排序提供者")
                    rerank_provider = MockRerankProvider()
            
            # 获取配置参数
            chunk_size = config['chunking']['chunk_size']
            overlap = config['chunking']['overlap']
            vector_store_path = config.get('vector_store_path', './data/vector_store_text_embedding')
            
            logger.info(f"使用配置参数 - 块大小: {chunk_size}, 重叠: {overlap}")
            logger.info(f"向量库存储路径: {vector_store_path}")
            
            # 创建RAG处理器
            rag_processor = RAGProcessor(
                embedding_provider=embedding_provider,
                chunk_size=chunk_size,
                overlap=overlap,
                vector_store_path=vector_store_path,
                use_law_chunker=use_law_chunker,
                rerank_provider=rerank_provider
            )
            
            logger.info("RAG处理器初始化完成")
            return rag_processor
        except Exception as e:
            logger.error(f"初始化RAG处理器失败: {e}")
            raise


@app.route('/health', methods=['GET'])
def health_check():
    """健康检查接口"""
    return jsonify({
        "status": "healthy",
        "message": "RAG系统HTTP API服务运行正常"
    })


@app.route('/store', methods=['POST'])
def store_documents():
    """存储文档接口"""
    global rag_processor
    try:
        # 获取请求参数
        is_json_request = request.is_json
        use_law_chunker = False
        
        if is_json_request:
            data = request.get_json()
            use_law_chunker = data.get('use_law_chunker', False)
        elif request.form:
            # 对于表单请求，从form中获取参数
            use_law_chunker = request.form.get('use_law_chunker', 'false').lower() == 'true'
            # 在这种情况下，文档数据通常不会通过表单传递，所以这里主要是为了统一接口
        
        # 初始化RAG处理器
        if rag_processor is None:
            rag_processor = initialize_rag_processor(use_law_chunker=use_law_chunker)
        elif rag_processor.use_law_chunker != use_law_chunker:
            # 如果分块器类型不同，重新初始化
            rag_processor = initialize_rag_processor(use_law_chunker=use_law_chunker)
        
        # 检查请求数据
        if not is_json_request:
            return jsonify({"error": "请求必须是JSON格式"}), 400
        
        data = request.get_json()
        
        # 检查必需字段
        if 'documents' not in data:
            return jsonify({"error": "缺少documents字段"}), 400
        
        documents = data['documents']
        if not isinstance(documents, list):
            return jsonify({"error": "documents必须是一个文档列表"}), 400
        
        # 可选参数
        save_after_processing = data.get('save_after_processing', True)
        store_path = data.get('store_path')
        
        if store_path:
            rag_processor.vector_store_path = store_path
        
        # 处理文档
        num_processed = rag_processor.process_documents(documents, save_after_processing=save_after_processing)
        
        return jsonify({
            "success": True,
            "message": f"成功处理了 {num_processed} 个文本块",
            "processed_count": num_processed,
            "chunker_used": "law" if use_law_chunker else "standard"
        })
        
    except Exception as e:
        logger.error(f"存储文档时出错: {e}")
        return jsonify({"error": f"存储文档失败: {str(e)}"}), 500


@app.route('/search', methods=['POST'])
def search_documents():
    """搜索文档接口"""
    global rag_processor
    try:
        # 初始化RAG处理器
        if rag_processor is None:
            rag_processor = initialize_rag_processor()
        
        # 检查请求数据
        if not request.is_json:
            return jsonify({"error": "请求必须是JSON格式"}), 400
        
        data = request.get_json()
        
        # 检查必需字段
        if 'query' not in data:
            return jsonify({"error": "缺少query字段"}), 400
        
        query = data['query']
        top_k = data.get('top_k', 5)
        store_path = data.get('store_path')
        
        if store_path:
            rag_processor.vector_store_path = store_path
        
        # 执行搜索
        results = rag_processor.search(query, top_k=top_k)
        
        # 格式化结果
        formatted_results = []
        for result in results:
            formatted_results.append({
                "score": result['score'],
                "text": result['document']['text'],
                "doc_id": result['document'].get('doc_id', ''),
                "filename": result['document'].get('filename', ''),
                "file_type": result['document'].get('file_type', '')
            })
        
        return jsonify({
            "success": True,
            "query": query,
            "results": formatted_results,
            "count": len(formatted_results)
        })
        
    except ValueError as e:
        # 特别处理向量库不存在的错误
        if "向量库不存在" in str(e):
            return jsonify({"error": "向量库不存在，请先存储文档"}), 404
        else:
            logger.error(f"搜索文档时出错: {e}")
            return jsonify({"error": f"搜索文档失败: {str(e)}"}), 500
    except Exception as e:
        logger.error(f"搜索文档时出错: {e}")
        return jsonify({"error": f"搜索文档失败: {str(e)}"}), 500


@app.route('/search_rerank', methods=['POST'])
def search_documents_with_rerank():
    """带重排序的搜索文档接口"""
    global rag_processor
    try:
        # 获取请求参数
        use_rerank = True
        use_law_chunker = False  # 重排序功能不直接影响分块器的选择，但我们可以根据需要设置
        
        # 初始化RAG处理器
        if rag_processor is None:
            rag_processor = initialize_rag_processor(use_law_chunker=use_law_chunker, use_rerank=use_rerank)
        elif (rag_processor.rerank_provider is None) != (not use_rerank):
            # 如果重排序设置不匹配，重新初始化
            rag_processor = initialize_rag_processor(use_law_chunker=use_law_chunker, use_rerank=use_rerank)
        
        # 检查请求数据
        if not request.is_json:
            return jsonify({"error": "请求必须是JSON格式"}), 400
        
        data = request.get_json()
        
        # 检查必需字段
        if 'query' not in data:
            return jsonify({"error": "缺少query字段"}), 400
        
        query = data['query']
        top_k = data.get('top_k', 5)
        rerank_top_k = data.get('rerank_top_k', 10)  # 重排序时考虑的文档数量
        store_path = data.get('store_path')
        
        if store_path:
            rag_processor.vector_store_path = store_path
        
        # 执行带重排序的搜索
        results = rag_processor.search(query, top_k=top_k, use_rerank=True, rerank_top_k=rerank_top_k)
        
        # 格式化结果
        formatted_results = []
        for result in results:
            result_entry = {
                "score": result['score'],
                "text": result['document']['text'],
                "doc_id": result['document'].get('doc_id', ''),
                "filename": result['document'].get('filename', ''),
                "file_type": result['document'].get('file_type', '')
            }
            
            # 如果有原始分数，也包含进去
            if 'original_score' in result:
                result_entry["original_score"] = result['original_score']
            
            formatted_results.append(result_entry)
        
        return jsonify({
            "success": True,
            "query": query,
            "results": formatted_results,
            "count": len(formatted_results),
            "with_rerank": True
        })
        
    except ValueError as e:
        # 特别处理向量库不存在的错误
        if "向量库不存在" in str(e):
            return jsonify({"error": "向量库不存在，请先存储文档"}), 404
        else:
            logger.error(f"搜索文档时出错: {e}")
            return jsonify({"error": f"搜索文档失败: {str(e)}"}), 500
    except Exception as e:
        logger.error(f"搜索文档时出错: {e}")
        return jsonify({"error": f"搜索文档失败: {str(e)}"}), 500


@app.route('/clear', methods=['POST'])
def clear_vector_store():
    """清空向量库接口"""
    global rag_processor
    try:
        # 初始化RAG处理器
        if rag_processor is None:
            rag_processor = initialize_rag_processor()
        
        store_path = None
        if request.is_json:
            data = request.get_json()
            if data:  # 确保data不为None
                store_path = data.get('store_path')
        
        if store_path:
            rag_processor.vector_store_path = store_path
        
        # 清空向量库
        rag_processor.clear_vector_store()
        
        # 保存清空的向量库 - 为了避免在向量库未初始化时出错，我们先检查是否存在
        try:
            rag_processor.save_vector_store()
        except ValueError as ve:
            if "没有可保存的向量库" in str(ve):
                # 如果向量库未初始化，创建一个新的空向量库并保存
                from src.vector_store import VectorStore
                rag_processor.vector_store = VectorStore(dimension=rag_processor.dimension or 1024)
                rag_processor.save_vector_store()
            else:
                raise  # 重新抛出其他ValueError异常
        
        return jsonify({
            "success": True,
            "message": "向量库已清空并保存"
        })
        
    except Exception as e:
        logger.error(f"清空向量库时出错: {e}")
        return jsonify({"error": f"清空向量库失败: {str(e)}"}), 500


@app.route('/upload_store', methods=['POST'])
def upload_and_store_documents():
    """上传并存储文档接口 - 支持文件上传"""
    global rag_processor
    try:
        # 获取请求参数
        use_law_chunker = request.form.get('use_law_chunker', 'false').lower() == 'true'
        
        # 初始化RAG处理器
        if rag_processor is None:
            rag_processor = initialize_rag_processor(use_law_chunker=use_law_chunker)
        elif rag_processor.use_law_chunker != use_law_chunker:
            # 如果分块器类型不同，重新初始化
            rag_processor = initialize_rag_processor(use_law_chunker=use_law_chunker)
        
        # 检查是否有文件被上传
        if 'files' not in request.files:
            return jsonify({"error": "没有上传文件"}), 400
        
        uploaded_files = request.files.getlist('files')
        if not uploaded_files or all(f.filename == '' for f in uploaded_files):
            return jsonify({"error": "没有选择任何文件"}), 400
        
        # 可选参数
        save_after_processing = request.form.get('save_after_processing', 'true').lower() == 'true'
        store_path = request.form.get('store_path')
        
        if store_path:
            rag_processor.vector_store_path = store_path
        
        # 临时存储文件路径
        temp_file_paths = []
        
        # 保存上传的文件到临时位置
        for file in uploaded_files:
            if file and file.filename:
                filename = secure_filename(file.filename)
                # 创建临时文件
                import tempfile
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1])
                file.save(temp_file.name)
                temp_file_paths.append(temp_file.name)
        
        # 使用RAGProcessor处理上传的文件
        num_processed = rag_processor.process_documents_from_files(temp_file_paths, save_after_processing=save_after_processing)
        
        # 删除临时文件
        for temp_path in temp_file_paths:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        
        return jsonify({
            "success": True,
            "message": f"成功处理了 {len(uploaded_files)} 个文件，生成了 {num_processed} 个文本块",
            "file_count": len(uploaded_files),
            "processed_count": num_processed,
            "chunker_used": "law" if use_law_chunker else "standard"
        })
        
    except Exception as e:
        logger.error(f"上传并存储文档时出错: {e}")
        return jsonify({"error": f"上传并存储文档失败: {str(e)}"}), 500


@app.route('/chunk_test', methods=['POST'])
def test_chunking():
    """测试文档分块功能 - 返回分块结果而不存储"""
    try:
        # 检查请求数据
        if not request.is_json:
            return jsonify({"error": "请求必须是JSON格式"}), 400
        
        data = request.get_json()
        
        # 检查必需字段
        if 'text' not in data:
            return jsonify({"error": "缺少text字段"}), 400
        
        text = data['text']
        filename = data.get('filename', 'test_document.txt')
        use_law_chunker = data.get('use_law_chunker', False)
        chunk_size = data.get('chunk_size', 512)
        overlap = data.get('overlap', 50)
        
        # 创建临时文档对象
        temp_document = {
            'doc_id': 'test_doc',
            'filename': filename,
            'file_type': 'txt',
            'text': text,
            'char_count': len(text)
        }
        
        # 根据参数选择分块器
        if use_law_chunker:
            chunker = LawDocumentChunker(chunk_size=chunk_size, overlap=overlap)
        else:
            chunker = DocumentChunker(chunk_size=chunk_size, overlap=overlap)
        
        # 执行分块
        chunks = chunker.chunk_documents([temp_document])
        
        # 格式化返回结果
        formatted_chunks = []
        for i, chunk in enumerate(chunks):
            formatted_chunks.append({
                "chunk_id": i + 1,
                "text": chunk['text'][:200] + "..." if len(chunk['text']) > 200 else chunk['text'],  # 截取前200个字符作为预览
                "full_text_length": len(chunk['text']),
                "semantic_boundary": chunk.get('semantic_boundary', 'content'),
                "section_path": chunk.get('section_path', []),
                "header": chunk.get('header', ''),
                "char_count": chunk.get('char_count', len(chunk['text']))
            })
        
        return jsonify({
            "success": True,
            "chunker_used": "law" if use_law_chunker else "standard",
            "original_text_length": len(text),
            "chunks_count": len(chunks),
            "chunks": formatted_chunks
        })
        
    except Exception as e:
        logger.error(f"测试分块时出错: {e}")
        return jsonify({"error": f"测试分块失败: {str(e)}"}), 500


@app.route('/chunk_test_upload', methods=['POST'])
def test_chunking_upload():
    """上传文件并测试文档分块功能 - 返回分块结果而不存储"""
    try:
        # 检查是否有文件被上传
        if 'file' not in request.files:
            return jsonify({"error": "没有上传文件"}), 400
        
        uploaded_file = request.files['file']
        if not uploaded_file or uploaded_file.filename == '':
            return jsonify({"error": "没有选择文件"}), 400
        
        # 获取其他参数
        use_law_chunker = request.form.get('use_law_chunker', 'false').lower() == 'true'
        chunk_size = int(request.form.get('chunk_size', 512))
        overlap = int(request.form.get('overlap', 50))
        
        # 保存上传的文件到临时位置
        import tempfile
        import os
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.filename)[1])
        uploaded_file.save(temp_file.name)
        
        try:
            # 使用文档处理器读取文件内容
            from src.document_processor import process_uploaded_documents
            file_paths = [temp_file.name]
            processed_docs = process_uploaded_documents(file_paths)
            
            if not processed_docs:
                return jsonify({"error": "无法处理上传的文件"}), 400
            
            # 获取文档内容
            doc = processed_docs[0]
            text = doc['text']
            filename = doc['filename']
            
            # 创建临时文档对象
            temp_document = {
                'doc_id': 'test_doc',
                'filename': filename,
                'file_type': doc['file_type'],
                'text': text,
                'char_count': len(text)
            }
            
            # 根据参数选择分块器
            if use_law_chunker:
                chunker = LawDocumentChunker(chunk_size=chunk_size, overlap=overlap)
            else:
                chunker = DocumentChunker(chunk_size=chunk_size, overlap=overlap)
            
            # 执行分块
            chunks = chunker.chunk_documents([temp_document])
            
            # 格式化返回结果
            formatted_chunks = []
            for i, chunk in enumerate(chunks):
                formatted_chunks.append({
                    "chunk_id": i + 1,
                    "text": chunk['text'][:200] + "..." if len(chunk['text']) > 200 else chunk['text'],  # 截取前200个字符作为预览
                    "full_text_length": len(chunk['text']),
                    "semantic_boundary": chunk.get('semantic_boundary', 'content'),
                    "section_path": chunk.get('section_path', []),
                    "header": chunk.get('header', ''),
                    "char_count": chunk.get('char_count', len(chunk['text']))
                })
            
            return jsonify({
                "success": True,
                "filename": filename,
                "file_type": doc['file_type'],
                "chunker_used": "law" if use_law_chunker else "standard",
                "original_text_length": len(text),
                "chunks_count": len(chunks),
                "chunks": formatted_chunks
            })
            
        finally:
            # 删除临时文件
            try:
                os.unlink(temp_file.name)
            except OSError:
                pass
        
    except Exception as e:
        logger.error(f"上传并测试分块时出错: {e}")
        return jsonify({"error": f"上传并测试分块失败: {str(e)}"}), 500


@app.route('/info', methods=['GET'])
def get_info():
    """获取系统信息"""
    global rag_processor
    try:
        if rag_processor is None:
            rag_processor = initialize_rag_processor()
        
        # 尝试加载向量库以获取信息
        try:
            rag_processor.load_vector_store()
            vector_count = rag_processor.vector_store.index.ntotal if rag_processor.vector_store else 0
            vector_store_status = "loaded"
        except:
            vector_count = 0
            vector_store_status = "not loaded or empty"
        
        return jsonify({
            "status": "running",
            "vector_store_status": vector_store_status,
            "vector_count": vector_count,
            "dimension": rag_processor.dimension or 1024
        })
    except Exception as e:
        logger.error(f"获取系统信息时出错: {e}")
        return jsonify({"error": f"获取系统信息失败: {str(e)}"}), 500


def run_server(host='0.0.0.0', port=8000):
    """运行HTTP服务器"""
    logger.info(f"启动HTTP API服务器，地址: {host}:{port}")
    
    # 预初始化RAG处理器
    try:
        initialize_rag_processor()
        logger.info("RAG处理器预初始化完成")
    except Exception as e:
        logger.error(f"RAG处理器预初始化失败: {e}")
        logger.info("将在首次请求时初始化")
    
    app.run(host=host, port=port, debug=False)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='RAG系统HTTP API服务器')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='服务器主机地址 (默认: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=8000, help='服务器端口 (默认: 8000)')
    args = parser.parse_args()
    
    run_server(host=args.host, port=args.port)