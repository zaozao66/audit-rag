import mimetypes
import os

from flask import Blueprint, current_app, jsonify, request, send_file

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


@documents_bp.route('/documents/by-filename', methods=['GET'])
def get_document_detail_by_filename():
    try:
        filename = str(request.args.get('filename', '') or '').strip()
        if not filename:
            return jsonify({"error": "缺少filename参数"}), 400

        service: RAGService = current_app.extensions['rag_service']
        rag_processor = service.get_processor()

        detail = rag_processor.get_document_detail_by_filename(filename)
        if not detail:
            return jsonify({"error": "文档不存在"}), 404

        return jsonify({
            "success": True,
            "document": detail
        })
    except Exception as e:
        current_app.logger.error("按文件名获取文档详情失败: %s", e)
        return jsonify({"error": str(e)}), 500


@documents_bp.route('/documents/id-by-filename', methods=['GET'])
def get_document_id_by_filename():
    try:
        filename = str(request.args.get('filename', '') or '').strip()
        if not filename:
            return jsonify({"error": "缺少filename参数"}), 400

        include_deleted = request.args.get('include_deleted', 'false').lower() == 'true'

        service: RAGService = current_app.extensions['rag_service']
        rag_processor = service.get_processor()

        result = rag_processor.get_document_id_by_filename(filename, include_deleted=include_deleted)
        if not result:
            return jsonify({"error": "文档不存在"}), 404

        return jsonify({
            "success": True,
            "data": result
        })
    except Exception as e:
        current_app.logger.error("按文件名获取文档ID失败: %s", e)
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


@documents_bp.route('/documents/<doc_id>/raw', methods=['GET'])
def get_document_raw(doc_id):
    try:
        service: RAGService = current_app.extensions['rag_service']
        rag_processor = service.get_processor()

        detail = rag_processor.get_document_detail(doc_id)
        if not detail:
            return jsonify({"error": "文档不存在"}), 404

        file_path = str(detail.get("file_path", "") or "").strip()
        candidates = []
        if file_path:
            if os.path.isabs(file_path):
                candidates.append(file_path)
            else:
                candidates.append(os.path.abspath(file_path))
                candidates.append(os.path.abspath(os.path.join(os.path.dirname(current_app.root_path), file_path)))
                candidates.append(os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(current_app.root_path)), file_path)))
        try:
            fallback_original = rag_processor._original_file_path(
                doc_id=doc_id,
                filename=detail.get("filename", ""),
                source_path=detail.get("filename", ""),
            )
            candidates.append(fallback_original)
        except Exception:
            pass

        resolved_path = next((p for p in candidates if p and os.path.exists(p)), "")
        if not resolved_path:
            return jsonify({"error": "原始文件不存在，请重新上传文档"}), 404

        mimetype, _ = mimetypes.guess_type(resolved_path)
        return send_file(
            resolved_path,
            mimetype=mimetype or "application/octet-stream",
            as_attachment=False,
            download_name=detail.get("filename") or os.path.basename(resolved_path),
            conditional=True,
        )
    except Exception as e:
        current_app.logger.error("获取原始文件失败: %s", e)
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
