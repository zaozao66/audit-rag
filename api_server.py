"""
RAG系统 - HTTP API接口
支持通过HTTP请求进行文档存储、搜索和清除操作
"""

import logging
import json
import os
import sys
from typing import Dict, Any, List
from flask import Flask, request, jsonify, Response
from werkzeug.utils import secure_filename

# 添加src目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from config_loader import load_config
from embedding_providers import TextEmbeddingProvider
from rag_processor import RAGProcessor, process_user_uploaded_documents, SmartChunker
from document_chunker import DocumentChunker
from law_document_chunker import LawDocumentChunker
from audit_report_chunker import AuditReportChunker
from audit_issue_chunker import AuditIssueChunker
from rerank_provider import AliyunRerankProvider
from llm_provider import create_llm_provider

# 配置日志
# 根据环境决定日志文件位置
env = os.getenv('ENVIRONMENT', 'development')
if env == 'production':
    log_file = '/data/appLogs/api_server.log'
else:
    log_file = './logs/api_server.log'

# 创建日志目录（如果不存在）
log_dir = os.path.dirname(log_file)
if log_dir and not os.path.exists(log_dir):
    os.makedirs(log_dir, exist_ok=True)

# 配置日志处理器
file_handler = logging.FileHandler(log_file, encoding='utf-8')
console_handler = logging.StreamHandler()

# 设置日志格式
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# 配置logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# 创建Flask应用
app = Flask(__name__)

# 全局变量存储RAG处理器实例
rag_processor = None


def initialize_rag_processor(chunker_type: str = None, use_rerank: bool = False, use_llm: bool = False):
    """初始化RAG处理器"""
    global rag_processor
    
    # 如果指定了分块器类型，且当前处理器类型不同，则重新初始化
    # 或者如果重排序设置不匹配，也重新初始化
    # 或者如果LLM设置不匹配，也重新初始化
    current_use_rerank = rag_processor is not None and rag_processor.rerank_provider is not None
    current_use_llm = rag_processor is not None and rag_processor.llm_provider is not None
    if rag_processor is not None:
        type_mismatch = chunker_type is not None and rag_processor.chunker_type != chunker_type
        rerank_mismatch = current_use_rerank != use_rerank
        llm_mismatch = current_use_llm != use_llm
        if type_mismatch or rerank_mismatch or llm_mismatch:
            rag_processor = None
    
    if rag_processor is None:
        try:
            # 加载配置
            logger.info("加载配置文件...")
            config = load_config()
            
            # 确定分块器类型：优先使用传入的，否则使用配置中的
            if chunker_type is None:
                chunker_type = config.get('chunking', {}).get('chunker_type', 'smart')
            
            # 获取环境信息
            env = config.get('environment', 'development')
            logger.info(f"当前运行环境: {env}")
            
            logger.info("创建嵌入提供者...")
            embedding_config = config['embedding_model']
            api_key = embedding_config['api_key']
            endpoint = embedding_config['endpoint']
            model_name = embedding_config['model_name']
            ssl_verify = embedding_config.get('ssl_verify', True)
            
            # 创建嵌入提供者，支持SSL验证控制
            embedding_provider = TextEmbeddingProvider(
                api_key=api_key,
                endpoint=endpoint,
                model_name=model_name,
                ssl_verify=ssl_verify,
                env=env
            )
            
            # 创建LLM提供者
            llm_provider = None
            if use_llm:
                logger.info("创建LLM提供者...")
                try:
                    llm_config = config.get('llm_model', {})
                    if 'api_key' in llm_config and llm_config['api_key'] and llm_config['api_key'] != 'YOUR_DEEPSEEK_API_KEY_HERE':
                        llm_provider = create_llm_provider(llm_config)
                    else:
                        logger.warning("LLM API密钥未配置，LLM功能将被禁用")
                except Exception as e:
                    logger.error(f"创建LLM提供者失败: {e}")
                    raise
            
            # 创建重排序提供者
            rerank_provider = None
            if use_rerank:
                logger.info("创建重排序提供者...")
                try:
                    rerank_config = config.get('rerank_model', {})
                    
                    if 'api_key' in rerank_config and rerank_config['api_key']:
                        ssl_verify_rerank = rerank_config.get('ssl_verify', True)
                        # 不再使用硬编码的默认值，因为在配置文件中已经定义了正确的值
                        endpoint = rerank_config.get('endpoint')
                        if not endpoint:
                            # 如果配置中没有指定端点，使用空字符串，让AliyunRerankProvider使用其默认值
                            endpoint = 'https://dashscope.aliyuncs.com/api/v1/services/rerank/text-retrieve-rerank'
                        rerank_provider = AliyunRerankProvider(
                            api_key=rerank_config['api_key'],
                            model_name=rerank_config.get('model_name', 'gte-rerank'),
                            endpoint=endpoint,
                            ssl_verify=ssl_verify_rerank,
                            env=config.get('environment', 'development')
                        )
                    else:
                        logger.warning("重排序API密钥未配置，使用模拟重排序提供者")
                        rerank_provider = MockRerankProvider()
                except Exception as e:
                    logger.error(f"创建重排序提供者失败: {e}")
                    raise  # 实现 fail-fast 行为，直接抛出异常
            
            # 获取配置参数
            chunk_size = config['chunking']['chunk_size']
            overlap = config['chunking']['overlap']
            vector_store_path = config.get('vector_store_path', './data/vector_store_text_embedding')
            # 默认分块器类型
            chunker_type = config.get('chunking', {}).get('chunker_type', 'smart')
            
            logger.info(f"使用配置参数 - 块大小: {chunk_size}, 重叠: {overlap}, 分块器类型: {chunker_type}")
            logger.info(f"向量库存储路径: {vector_store_path}")
            
            # 创建RAG处理器
            rag_processor = RAGProcessor(
                embedding_provider=embedding_provider,
                chunk_size=chunk_size,
                overlap=overlap,
                vector_store_path=vector_store_path,
                chunker_type=chunker_type,
                rerank_provider=rerank_provider,
                llm_provider=llm_provider
            )
            
            logger.info(f"RAG处理器初始化完成，环境: {env}")
        except Exception as e:
            logger.error(f"初始化RAG处理器失败: {e}")
            raise
    
    return rag_processor


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
        chunker_type = 'smart'
        
        if is_json_request:
            data = request.get_json()
            chunker_type = data.get('chunker_type') or data.get('chunker-type') or 'smart'
            if chunker_type == 'law': chunker_type = 'regulation'
            if chunker_type == 'audit': chunker_type = 'audit_report'
            if chunker_type == 'issue': chunker_type = 'audit_issue'
        elif request.form:
            # 对于表单请求，从form中获取参数
            chunker_type = request.form.get('chunker_type') or request.form.get('chunker-type') or 'smart'
            if chunker_type == 'law': chunker_type = 'regulation'
            if chunker_type == 'audit': chunker_type = 'audit_report'
            if chunker_type == 'issue': chunker_type = 'audit_issue'
        
        # 初始化RAG处理器
        if rag_processor is None or (chunker_type != 'smart' and rag_processor.chunker_type != chunker_type):
            rag_processor = initialize_rag_processor(chunker_type=chunker_type)
        
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
            "chunker_used": chunker_type
        })
        
    except Exception as e:
        logger.error(f"存储文档时出错: {e}")
        return jsonify({"error": f"存储文档失败: {str(e)}"}), 500


def _format_search_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """统一搜索结果格式化逻辑"""
    formatted = []
    for res in results:
        doc = res['document']
        entry = {
            "score": res['score'],
            "text": doc['text'],
            "doc_id": doc.get('doc_id', ''),
            "filename": doc.get('filename', ''),
            "file_type": doc.get('file_type', ''),
            "doc_type": doc.get('doc_type', ''),
            "title": doc.get('title', '')
        }
        if 'original_score' in res:
            entry["original_score"] = res['original_score']
        formatted.append(entry)
    return formatted


@app.route('/search_with_intent', methods=['POST'])
def search_with_intent():
    """带意图识别的智能搜索接口"""
    global rag_processor
    try:
        rag_processor = initialize_rag_processor(use_rerank=True, use_llm=True)
        data = request.get_json()
        query = data.get('query')
        if not query:
            return jsonify({"error": "缺少query参数"}), 400
        
        result = rag_processor.search_with_intent(query, use_rerank=True)
        return jsonify({
            "success": True,
            "query": query,
            "intent": result['intent'],
            "intent_reason": result['intent_reason'],
            "suggested_top_k": result['suggested_top_k'],
            "results": _format_search_results(result['search_results'])
        })
    except Exception as e:
        logger.error(f"智能搜索失败: {e}")
        return jsonify({"error": f"搜索失败: {str(e)}"}), 500


@app.route('/ask', methods=['POST'])
def ask_with_llm():
    """带LLM回答的问答接口"""
    global rag_processor
    try:
        rag_processor = initialize_rag_processor(use_rerank=True, use_llm=True)
        data = request.get_json()
        if not data or 'query' not in data:
            return jsonify({"error": "缺少query字段"}), 400
        
        query = data['query']
        top_k = data.get('top_k', 5)
        
        result = rag_processor.search_with_llm_answer(query, top_k=top_k)
        
        return jsonify({
            "success": True,
            "query": query,
            "intent": result.get('intent', 'unknown'),
            "answer": result['answer'],
            "search_results": _format_search_results(result['search_results']),
            "llm_usage": result['llm_usage'],
            "model": result['model']
        })
    except Exception as e:
        logger.error(f"LLM问答出错: {e}")
        return jsonify({"error": f"问答失败: {str(e)}"}), 500
        
    except ValueError as e:
        if "LLM功能未启用" in str(e):
            return jsonify({"error": "LLM功能未配置，请在config.json中配置LLM API密钥"}), 503
        elif "向量库不存在" in str(e):
            return jsonify({"error": "向量库不存在，请先存储文档"}), 404
        else:
            logger.error(f"LLM问答时出错: {e}")
            return jsonify({"error": f"LLM问答失败: {str(e)}"}), 500
    except Exception as e:
        logger.error(f"LLM问答时出错: {e}")
        return jsonify({"error": f"LLM问答失败: {str(e)}"}), 500


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
        # 获取参数并进行映射
        chunker_type = request.form.get('chunker_type') or request.form.get('chunker-type') or 'smart'
        
        # 统一映射：law -> regulation, audit -> audit_report, issue -> audit_issue
        if chunker_type == 'law': chunker_type = 'regulation'
        if chunker_type == 'audit': chunker_type = 'audit_report'
        if chunker_type == 'issue': chunker_type = 'audit_issue'
        
        # 初始化RAG处理器
        if rag_processor is None or (chunker_type != 'smart' and rag_processor.chunker_type != chunker_type):
            rag_processor = initialize_rag_processor(chunker_type=chunker_type)
        
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
        
        # 临时存储文件路径和原始文件名
        temp_file_paths = []
        original_filenames = []
        
        # 保存上传的文件到临时位置
        for file in uploaded_files:
            if file and file.filename:
                # 直接使用原始文件名，保留中文字符
                # 只替换路径分隔符以防止路径遍历攻击
                filename = file.filename.replace('/', '_').replace('\\', '_').replace('\0', '')
                original_filenames.append(filename) # 记录原始文件名
                # 创建临时文件
                import tempfile
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1])
                file.save(temp_file.name)
                temp_file_paths.append(temp_file.name)
        
        # 获取文档类型和标题参数
        doc_type = request.form.get('doc_type', 'internal_regulation')
        title = request.form.get('title', None)
        
        # 使用RAGProcessor处理上传的文件
        num_processed = rag_processor.process_documents_from_files(
            temp_file_paths, 
            save_after_processing=save_after_processing, 
            doc_type=doc_type, 
            title=title,
            original_filenames=original_filenames # 传递原始文件名
        )
        
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
            "chunker_used": chunker_type
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
        chunker_type = data.get('chunker_type') or data.get('chunker-type') or 'smart'
        doc_type = data.get('doc_type')
        
        # 映射
        if chunker_type == 'law': chunker_type = 'regulation'
        if chunker_type == 'audit': chunker_type = 'audit_report'
        if chunker_type == 'issue': chunker_type = 'audit_issue'
        
        if not doc_type:
            if chunker_type == 'regulation': doc_type = 'internal_regulation'
            elif chunker_type == 'audit_report': doc_type = 'internal_report'
            elif chunker_type == 'audit_issue': doc_type = 'audit_issue'
            else: doc_type = 'internal_regulation'
            
        chunk_size = data.get('chunk_size', 512)
        overlap = data.get('overlap', 50)
        
        # 创建临时文档对象
        temp_document = {
            'doc_id': 'test_doc',
            'filename': filename,
            'file_type': 'txt',
            'text': text,
            'doc_type': doc_type, # 传递 doc_type
            'char_count': len(text)
        }
        
        # 根据参数选择分块器
        if chunker_type == "regulation" or chunker_type == "law":
            chunker = LawDocumentChunker(chunk_size=chunk_size, overlap=overlap)
        elif chunker_type == "audit_report" or chunker_type == "audit":
            chunker = AuditReportChunker(chunk_size=chunk_size, overlap=overlap)
        elif chunker_type == "audit_issue" or chunker_type == "issue":
            chunker = AuditIssueChunker(chunk_size=chunk_size, overlap=overlap)
        elif chunker_type == "smart":
            chunker = SmartChunker(chunk_size=chunk_size, overlap=overlap)
        else:
            chunker = DocumentChunker(chunk_size=chunk_size, overlap=overlap)
        
        # 执行分块
        chunks = chunker.chunk_documents([temp_document])
        
        # 格式化返回结果
        formatted_chunks = []
        for i, chunk in enumerate(chunks):
            formatted_chunks.append({
                "chunk_id": i + 1,
                "text": chunk['text'],
                "full_text_length": len(chunk['text']),
                "semantic_boundary": chunk.get('semantic_boundary', 'content'),
                "section_path": chunk.get('section_path', []),
                "header": chunk.get('header', ''),
                "char_count": chunk.get('char_count', len(chunk['text']))
            })
        
        return jsonify({
            "success": True,
            "chunker_used": chunker_type,
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
        chunker_type = request.form.get('chunker_type') or request.form.get('chunker-type') or 'smart'
        doc_type = request.form.get('doc_type')
        
        # 统一映射
        if chunker_type == 'law': chunker_type = 'regulation'
        if chunker_type == 'audit': chunker_type = 'audit_report'
        if chunker_type == 'issue': chunker_type = 'audit_issue'
        
        # 如果未指定 doc_type，根据 chunker_type 推断
        if not doc_type:
            if chunker_type == 'regulation': doc_type = 'internal_regulation'
            elif chunker_type == 'audit_report': doc_type = 'internal_report'
            elif chunker_type == 'audit_issue': doc_type = 'audit_issue'
            else: doc_type = 'internal_regulation'
            
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
            # 传递 doc_type，确保如果是 audit_issue 会调用表格提取逻辑
            processed_docs = process_uploaded_documents(file_paths, doc_type=doc_type)
            
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
                'doc_type': doc.get('doc_type', doc_type), # 传递 doc_type
                'text': text,
                'char_count': len(text)
            }
            
            # 根据参数选择分块器
            if chunker_type == "regulation" or chunker_type == "law":
                chunker = LawDocumentChunker(chunk_size=chunk_size, overlap=overlap)
            elif chunker_type == "audit_report" or chunker_type == "audit":
                chunker = AuditReportChunker(chunk_size=chunk_size, overlap=overlap)
            elif chunker_type == "audit_issue" or chunker_type == "issue":
                chunker = AuditIssueChunker(chunk_size=chunk_size, overlap=overlap)
            elif chunker_type == "smart":
                chunker = SmartChunker(chunk_size=chunk_size, overlap=overlap)
            else:
                chunker = DocumentChunker(chunk_size=chunk_size, overlap=overlap)
            
            # 执行分块
            chunks = chunker.chunk_documents([temp_document])
            
            # 格式化返回结果
            formatted_chunks = []
            for i, chunk in enumerate(chunks):
                formatted_chunks.append({
                    "chunk_id": i + 1,
                    "text": chunk['text'],
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
                "chunker_used": chunker_type,
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
            "dimension": rag_processor.dimension or 1024,
            "chunker_type": rag_processor.chunker_type,
            "embedding_model": rag_processor.embedding_provider.model_name if hasattr(rag_processor.embedding_provider, 'model_name') else 'unknown',
            "rerank_enabled": rag_processor.rerank_provider is not None
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
    parser.add_argument('--env', type=str, default=None, help='运行环境 (production 或 development)')
    args = parser.parse_args()
    
    # 如果命令行指定了环境，则设置环境变量
    if args.env:
        import os
        os.environ['ENVIRONMENT'] = args.env
    
    run_server(host=args.host, port=args.port)