from flask import Blueprint, current_app, jsonify, request

from src.api.services.rag_service import RAGService


documents_bp = Blueprint('documents', __name__)


@documents_bp.route('/documents', methods=['GET'])
def list_documents():
    try:
        doc_type = request.args.get('doc_type')
        keyword = request.args.get('keyword')
        include_deleted = request.args.get('include_deleted', 'false').lower() == 'true'

        service: RAGService = current_app.extensions['rag_service']
        rag_processor = service.get_processor()

        documents = rag_processor.list_documents(doc_type=doc_type, keyword=keyword, include_deleted=include_deleted)
        return jsonify({
            "success": True,
            "count": len(documents),
            "documents": documents
        })
    except Exception as e:
        current_app.logger.error("获取文档列表失败: %s", e)
        return jsonify({"error": str(e)}), 500


@documents_bp.route('/documents', methods=['DELETE'])
def clear_all_documents():
    try:
        service: RAGService = current_app.extensions['rag_service']
        rag_processor = service.get_processor()
        result = rag_processor.clear_all_documents()
        return jsonify(result)
    except Exception as e:
        current_app.logger.error("清空所有文档失败: %s", e)
        return jsonify({"error": str(e)}), 500


@documents_bp.route('/documents/<doc_id>', methods=['GET'])
def get_document_detail(doc_id):
    try:
        service: RAGService = current_app.extensions['rag_service']
        rag_processor = service.get_processor()

        detail = rag_processor.get_document_detail(doc_id)
        if not detail:
            return jsonify({"error": "文档不存在"}), 404

        return jsonify({
            "success": True,
            "document": detail
        })
    except Exception as e:
        current_app.logger.error("获取文档详情失败: %s", e)
        return jsonify({"error": str(e)}), 500


@documents_bp.route('/documents/<doc_id>', methods=['DELETE'])
def delete_document(doc_id):
    try:
        service: RAGService = current_app.extensions['rag_service']
        rag_processor = service.get_processor()

        result = rag_processor.delete_document(doc_id)
        if not result['success']:
            return jsonify(result), 404

        return jsonify(result)
    except Exception as e:
        current_app.logger.error("删除文档失败: %s", e)
        return jsonify({"error": str(e)}), 500


@documents_bp.route('/documents/<doc_id>/chunks', methods=['GET'])
def get_document_chunks(doc_id):
    try:
        service: RAGService = current_app.extensions['rag_service']
        rag_processor = service.get_processor()

        include_text = request.args.get('include_text', 'true').lower() == 'true'
        result = rag_processor.get_document_chunks(doc_id, include_text=include_text)

        if "error" in result:
            return jsonify(result), 404

        return jsonify({
            "success": True,
            "data": result
        })
    except Exception as e:
        current_app.logger.error("获取分块列表失败: %s", e)
        return jsonify({"error": str(e)}), 500


@documents_bp.route('/documents/stats', methods=['GET'])
def get_document_stats():
    try:
        service: RAGService = current_app.extensions['rag_service']
        rag_processor = service.get_processor()

        stats = rag_processor.get_document_stats()
        return jsonify({
            "success": True,
            "stats": stats
        })
    except Exception as e:
        current_app.logger.error("获取统计信息失败: %s", e)
        return jsonify({"error": str(e)}), 500
