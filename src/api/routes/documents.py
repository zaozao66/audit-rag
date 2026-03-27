import io
import mimetypes
import os

from flask import Blueprint, current_app, jsonify, request, send_file

from src.api.routes.scope_utils import extract_scope_from_request
from src.api.services.file_storage_service import (
    FILE_BLOB_MISSING_MESSAGE,
    FILE_NOT_FOUND_MESSAGE,
    FileBlobMissingError,
    FileRecordNotFoundError,
)
from src.api.services.rag_service import RAGService


documents_bp = Blueprint('documents', __name__)


def _to_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'y', 'on')
    return default


def _get_scoped_processor(service: RAGService, json_data=None):
    scope = extract_scope_from_request(request, json_data=json_data)
    return service.get_processor(scope=scope)


@documents_bp.route('/documents', methods=['GET'])
def list_documents():
    try:
        doc_type = request.args.get('doc_type')
        keyword = request.args.get('keyword')
        include_deleted = request.args.get('include_deleted', 'false').lower() == 'true'

        service: RAGService = current_app.extensions['rag_service']
        rag_processor = _get_scoped_processor(service)

        documents = rag_processor.list_documents(doc_type=doc_type, keyword=keyword, include_deleted=include_deleted)
        return jsonify({
            "success": True,
            "count": len(documents),
            "documents": documents
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error("获取文档列表失败: %s", e)
        return jsonify({"error": str(e)}), 500


@documents_bp.route('/regulation-groups', methods=['GET'])
def list_regulation_groups():
    try:
        keyword = request.args.get('keyword')
        include_deleted = request.args.get('include_deleted', 'false').lower() == 'true'

        service: RAGService = current_app.extensions['rag_service']
        rag_processor = _get_scoped_processor(service)

        groups = rag_processor.list_regulation_groups(keyword=keyword, include_deleted=include_deleted)
        return jsonify({
            "success": True,
            "count": len(groups),
            "groups": groups,
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error("获取制度分组失败: %s", e)
        return jsonify({"error": str(e)}), 500


@documents_bp.route('/regulation-groups/<group_id>/versions', methods=['GET'])
def list_regulation_group_versions(group_id):
    try:
        include_deleted = request.args.get('include_deleted', 'false').lower() == 'true'

        service: RAGService = current_app.extensions['rag_service']
        rag_processor = _get_scoped_processor(service)

        versions = rag_processor.list_regulation_versions(group_id=group_id, include_deleted=include_deleted)
        return jsonify({
            "success": True,
            "group_id": group_id,
            "count": len(versions),
            "versions": versions,
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error("获取制度版本列表失败: %s", e)
        return jsonify({"error": str(e)}), 500


@documents_bp.route('/regulation-compare', methods=['POST'])
def compare_regulation_versions():
    try:
        data = request.get_json(silent=True) or {}
        left_doc_id = str(data.get('left_doc_id', '') or data.get('doc_id_a', '') or '').strip()
        right_doc_id = str(data.get('right_doc_id', '') or data.get('doc_id_b', '') or '').strip()
        group_id = str(data.get('group_id', '') or '').strip()
        include_unchanged = _to_bool(data.get('include_unchanged', False), default=False)
        keyword = str(data.get('keyword', '') or '').strip()
        try:
            limit = int(data.get('limit', 500))
        except (TypeError, ValueError):
            limit = 500

        service: RAGService = current_app.extensions['rag_service']
        rag_processor = _get_scoped_processor(service, json_data=data)

        # 支持仅传 group_id 自动比较最新两个版本（最新 vs 次新）
        if group_id and (not left_doc_id or not right_doc_id):
            versions = rag_processor.list_regulation_versions(group_id=group_id, include_deleted=False)
            if len(versions) < 2:
                return jsonify({"error": "该制度组历史版本不足2个，无法对比"}), 400
            right_doc_id = right_doc_id or str(versions[0].get('doc_id', '') or '').strip()
            left_doc_id = left_doc_id or str(versions[1].get('doc_id', '') or '').strip()

        if not left_doc_id or not right_doc_id:
            return jsonify({"error": "缺少left_doc_id/right_doc_id"}), 400

        result = rag_processor.compare_regulation_versions(
            left_doc_id=left_doc_id,
            right_doc_id=right_doc_id,
            include_unchanged=include_unchanged,
            keyword=keyword,
            limit=limit,
        )
        return jsonify({
            "success": True,
            "data": result,
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error("制度版本对比失败: %s", e)
        return jsonify({"error": str(e)}), 500


@documents_bp.route('/documents', methods=['DELETE'])
def clear_all_documents():
    try:
        service: RAGService = current_app.extensions['rag_service']
        rag_processor = _get_scoped_processor(service)
        result = rag_processor.clear_all_documents()
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error("清空所有文档失败: %s", e)
        return jsonify({"error": str(e)}), 500


@documents_bp.route('/documents/<doc_id>', methods=['GET'])
def get_document_detail(doc_id):
    try:
        service: RAGService = current_app.extensions['rag_service']
        rag_processor = _get_scoped_processor(service)

        detail = rag_processor.get_document_detail(doc_id)
        if not detail:
            return jsonify({"error": "文档不存在"}), 404

        return jsonify({
            "success": True,
            "document": detail
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
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
        rag_processor = _get_scoped_processor(service)

        detail = rag_processor.get_document_detail_by_filename(filename)
        if not detail:
            return jsonify({"error": "文档不存在"}), 404

        return jsonify({
            "success": True,
            "document": detail
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
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
        rag_processor = _get_scoped_processor(service)

        result = rag_processor.get_document_id_by_filename(filename, include_deleted=include_deleted)
        if not result:
            return jsonify({"error": "文档不存在"}), 404

        return jsonify({
            "success": True,
            "data": result
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error("按文件名获取文档ID失败: %s", e)
        return jsonify({"error": str(e)}), 500


@documents_bp.route('/documents/<doc_id>', methods=['DELETE'])
def delete_document(doc_id):
    try:
        service: RAGService = current_app.extensions['rag_service']
        rag_processor = _get_scoped_processor(service)

        result = rag_processor.delete_document(doc_id)
        if not result['success']:
            return jsonify(result), 404

        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error("删除文档失败: %s", e)
        return jsonify({"error": str(e)}), 500


@documents_bp.route('/documents/<doc_id>/chunks', methods=['GET'])
def get_document_chunks(doc_id):
    try:
        service: RAGService = current_app.extensions['rag_service']
        rag_processor = _get_scoped_processor(service)

        include_text = request.args.get('include_text', 'true').lower() == 'true'
        result = rag_processor.get_document_chunks(doc_id, include_text=include_text)

        if "error" in result:
            return jsonify(result), 404

        return jsonify({
            "success": True,
            "data": result
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error("获取分块列表失败: %s", e)
        return jsonify({"error": str(e)}), 500


@documents_bp.route('/documents/<doc_id>/raw', methods=['GET'])
def get_document_raw(doc_id):
    try:
        service: RAGService = current_app.extensions['rag_service']
        rag_processor = _get_scoped_processor(service)

        detail = rag_processor.get_document_detail(doc_id)
        if not detail:
            return jsonify({"error": "文档不存在"}), 404

        storage_file_id = str(detail.get("storage_file_id", "") or "").strip()
        file_storage_service = current_app.extensions.get("file_storage_service")
        if storage_file_id and file_storage_service:
            try:
                local_path = file_storage_service.resolve_local_path(storage_file_id)
                if local_path and os.path.isfile(local_path):
                    mimetype, _ = mimetypes.guess_type(local_path)
                    return send_file(
                        local_path,
                        mimetype=mimetype or "application/octet-stream",
                        as_attachment=False,
                        download_name=detail.get("filename") or os.path.basename(local_path),
                        conditional=True,
                    )

                record, payload = file_storage_service.read_file_by_id(storage_file_id)
                mimetype, _ = mimetypes.guess_type(record.original_filename)
                return send_file(
                    io.BytesIO(payload),
                    mimetype=mimetype or "application/octet-stream",
                    as_attachment=False,
                    download_name=record.original_filename or detail.get("filename") or "document",
                    conditional=True,
                )
            except FileRecordNotFoundError:
                current_app.logger.error(
                    "读取文档原文件失败: storage_file_id=%s, %s",
                    storage_file_id,
                    FILE_NOT_FOUND_MESSAGE,
                )
                return jsonify({"error": FILE_NOT_FOUND_MESSAGE}), 404
            except FileBlobMissingError:
                current_app.logger.error(
                    "读取文档原文件失败: storage_file_id=%s, %s",
                    storage_file_id,
                    FILE_BLOB_MISSING_MESSAGE,
                )
                return jsonify({"error": FILE_BLOB_MISSING_MESSAGE}), 404

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
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error("获取原始文件失败: %s", e)
        return jsonify({"error": str(e)}), 500


@documents_bp.route('/documents/stats', methods=['GET'])
def get_document_stats():
    try:
        service: RAGService = current_app.extensions['rag_service']
        rag_processor = _get_scoped_processor(service)

        stats = rag_processor.get_document_stats()
        return jsonify({
            "success": True,
            "stats": stats
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error("获取统计信息失败: %s", e)
        return jsonify({"error": str(e)}), 500
