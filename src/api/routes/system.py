import os
from flask import Blueprint, current_app, jsonify, send_from_directory

from src.api.services.rag_service import RAGService


system_bp = Blueprint('system', __name__)


@system_bp.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "message": "RAG系统HTTP API服务运行正常"
    })


@system_bp.route('/info', methods=['GET'])
def get_info():
    try:
        service: RAGService = current_app.extensions['rag_service']
        rag_processor = service.get_processor()

        try:
            rag_processor.load_vector_store()
            vector_count = rag_processor.vector_store.index.ntotal if rag_processor.vector_store else 0
            vector_store_status = "loaded"
        except Exception:
            vector_count = 0
            vector_store_status = "not loaded or empty"

        doc_stats = rag_processor.get_document_stats() if hasattr(rag_processor, 'get_document_stats') else {}

        return jsonify({
            "status": "running",
            "vector_store_status": vector_store_status,
            "vector_count": vector_count,
            "dimension": rag_processor.dimension or 1024,
            "chunker_type": rag_processor.chunker_type,
            "embedding_model": rag_processor.embedding_provider.model_name if hasattr(rag_processor.embedding_provider, 'model_name') else 'unknown',
            "rerank_enabled": rag_processor.rerank_provider is not None,
            "document_stats": doc_stats
        })
    except Exception as e:
        current_app.logger.error("获取系统信息时出错: %s", e)
        return jsonify({"error": f"获取系统信息失败: {str(e)}"}), 500


@system_bp.route('/', defaults={'path': ''})
@system_bp.route('/<path:path>')
def serve_frontend(path):
    frontend_dist_dir = current_app.config.get('FRONTEND_DIST_DIR', '')

    if not os.path.isdir(frontend_dist_dir):
        return jsonify({"error": "前端资源不存在，请先执行 frontend 构建"}), 404

    if path:
        target = os.path.join(frontend_dist_dir, path)
        if os.path.isfile(target):
            return send_from_directory(frontend_dist_dir, path)

    index_path = os.path.join(frontend_dist_dir, 'index.html')
    if os.path.isfile(index_path):
        return send_from_directory(frontend_dist_dir, 'index.html')
    return jsonify({"error": "前端入口文件不存在，请重新构建前端"}), 404
