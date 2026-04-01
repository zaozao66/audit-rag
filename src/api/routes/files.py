import io
import mimetypes
import os
import tempfile
from typing import List, Optional

from flask import Blueprint, current_app, jsonify, request, send_file

from src.api.routes.scope_utils import extract_scope_from_request
from src.api.services.file_storage_service import (
    FILE_BLOB_MISSING_MESSAGE,
    FILE_NOT_FOUND_MESSAGE,
    FileBlobMissingError,
    FileRecordNotFoundError,
    FileStorageError,
    UnifiedFileStorageService,
)
from src.api.services.file_upload_session_service import (
    FileUploadSessionService,
    UploadSessionError,
    UploadSessionExpiredError,
    UploadSessionNotFoundError,
)


files_bp = Blueprint("files", __name__)


def _to_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "on")
    return default


def _normalize_domain(value: Optional[str]) -> Optional[str]:
    normalized = str(value or "").strip().lower()
    if normalized in {"", "*", "all"}:
        return None
    return normalized


def _query_domain() -> Optional[str]:
    return _normalize_domain(request.args.get("domain") or request.args.get("scope"))


def _file_storage_service() -> UnifiedFileStorageService:
    service = current_app.extensions.get("file_storage_service")
    if not service:
        raise RuntimeError("统一文件存储服务未初始化")
    return service


def _file_upload_session_service() -> FileUploadSessionService:
    service = current_app.extensions.get("file_upload_session_service")
    if not service:
        raise RuntimeError("文件分片上传服务未初始化")
    return service


def _request_value(name: str, default=None):
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        if name in payload:
            return payload.get(name)
    if name in request.form:
        return request.form.get(name)
    if name in request.args:
        return request.args.get(name)
    return default


@files_bp.route("/files/upload", methods=["POST"])
def upload_file():
    temp_paths: List[str] = []
    try:
        service = _file_storage_service()

        uploads = []
        if "files" in request.files:
            uploads.extend(request.files.getlist("files"))
        if "file" in request.files:
            uploads.append(request.files["file"])

        uploads = [item for item in uploads if item and item.filename]
        if not uploads:
            return jsonify({"error": "没有上传文件"}), 400

        domain = extract_scope_from_request(request) or _normalize_domain(request.form.get("domain")) or "unknown"
        records = []
        for upload in uploads:
            filename = str(upload.filename or "").replace("/", "_").replace("\\", "_").replace("\x00", "")
            suffix = os.path.splitext(filename)[1]
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix or ".bin")
            temp_paths.append(temp_file.name)
            upload.save(temp_file.name)
            temp_file.close()

            record = service.store_from_path(
                source_path=temp_file.name,
                original_filename=filename,
                domain=domain,
            )
            records.append(record.to_dict())

        return jsonify(
            {
                "success": True,
                "count": len(records),
                "records": records,
            }
        )
    except (FileStorageError, ValueError, RuntimeError) as e:
        current_app.logger.error("统一文件上传失败: %s", e)
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        current_app.logger.error("统一文件上传失败: %s", e, exc_info=True)
        return jsonify({"error": f"统一文件上传失败: {str(e)}"}), 500
    finally:
        for path in temp_paths:
            try:
                os.unlink(path)
            except OSError:
                pass


@files_bp.route("/files/upload/init", methods=["POST"])
def init_chunked_upload():
    try:
        service = _file_upload_session_service()
        filename = str(_request_value("filename", "") or "").strip()
        if not filename:
            return jsonify({"error": "缺少 filename 参数"}), 400

        file_size = int(_request_value("file_size", 0) or 0)
        total_chunks = int(_request_value("total_chunks", 0) or 0)
        if total_chunks <= 0:
            return jsonify({"error": "total_chunks 必须大于 0"}), 400

        content_type = str(_request_value("content_type", "") or "").strip()
        chunk_size = int(_request_value("chunk_size", 0) or 0) or None
        domain = extract_scope_from_request(request) or _normalize_domain(_request_value("domain")) or "unknown"
        upload = service.create_session(
            original_filename=filename,
            file_size=file_size,
            total_chunks=total_chunks,
            domain=domain,
            content_type=content_type,
            chunk_size=chunk_size,
        )
        return jsonify({"success": True, "upload": upload})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except (UploadSessionError, RuntimeError) as e:
        current_app.logger.error("初始化分片上传失败: %s", e)
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        current_app.logger.error("初始化分片上传失败: %s", e, exc_info=True)
        return jsonify({"error": f"初始化分片上传失败: {str(e)}"}), 500


@files_bp.route("/files/upload/chunk", methods=["POST"])
def upload_file_chunk():
    temp_paths: List[str] = []
    try:
        service = _file_upload_session_service()
        upload_id = str(_request_value("upload_id", "") or "").strip()
        if not upload_id:
            return jsonify({"error": "缺少 upload_id 参数"}), 400

        chunk_index = int(_request_value("chunk_index", -1) or -1)
        if chunk_index < 0:
            return jsonify({"error": "chunk_index 必须大于等于 0"}), 400

        upload = request.files.get("chunk") or request.files.get("file")
        if not upload:
            return jsonify({"error": "缺少 chunk 文件"}), 400

        suffix = os.path.splitext(str(upload.filename or ""))[1] or ".part"
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        temp_paths.append(temp_file.name)
        upload.save(temp_file.name)
        temp_file.close()

        status = service.save_chunk(upload_id=upload_id, chunk_index=chunk_index, source_path=temp_file.name)
        return jsonify({"success": True, "upload": status})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except UploadSessionNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except UploadSessionExpiredError as e:
        return jsonify({"error": str(e)}), 410
    except (UploadSessionError, RuntimeError) as e:
        current_app.logger.error("上传分片失败: %s", e)
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        current_app.logger.error("上传分片失败: %s", e, exc_info=True)
        return jsonify({"error": f"上传分片失败: {str(e)}"}), 500
    finally:
        for path in temp_paths:
            try:
                os.unlink(path)
            except OSError:
                pass


@files_bp.route("/files/upload/complete", methods=["POST"])
def complete_chunked_upload():
    try:
        upload_id = str(_request_value("upload_id", "") or "").strip()
        if not upload_id:
            return jsonify({"error": "缺少 upload_id 参数"}), 400

        session_service = _file_upload_session_service()
        storage_service = _file_storage_service()
        record = session_service.complete_session(upload_id=upload_id, storage_service=storage_service)
        return jsonify({"success": True, "count": 1, "records": [record]})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except UploadSessionNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except UploadSessionExpiredError as e:
        return jsonify({"error": str(e)}), 410
    except (UploadSessionError, FileStorageError, RuntimeError) as e:
        current_app.logger.error("完成分片上传失败: %s", e)
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        current_app.logger.error("完成分片上传失败: %s", e, exc_info=True)
        return jsonify({"error": f"完成分片上传失败: {str(e)}"}), 500


@files_bp.route("/files/upload/<upload_id>", methods=["GET"])
def get_chunked_upload_status(upload_id: str):
    try:
        status = _file_upload_session_service().get_session(upload_id)
        return jsonify({"success": True, "upload": status})
    except UploadSessionNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except UploadSessionExpiredError as e:
        return jsonify({"error": str(e)}), 410
    except (UploadSessionError, RuntimeError) as e:
        current_app.logger.error("获取分片上传状态失败: %s", e)
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        current_app.logger.error("获取分片上传状态失败: %s", e, exc_info=True)
        return jsonify({"error": f"获取分片上传状态失败: {str(e)}"}), 500


@files_bp.route("/files/upload/<upload_id>", methods=["DELETE"])
def abort_chunked_upload(upload_id: str):
    try:
        _file_upload_session_service().abort_session(upload_id)
        return jsonify({"success": True, "upload_id": upload_id})
    except UploadSessionNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except (UploadSessionError, RuntimeError) as e:
        current_app.logger.error("取消分片上传失败: %s", e)
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        current_app.logger.error("取消分片上传失败: %s", e, exc_info=True)
        return jsonify({"error": f"取消分片上传失败: {str(e)}"}), 500


@files_bp.route("/files", methods=["GET"])
def list_files():
    try:
        service = _file_storage_service()
        page = max(1, int(request.args.get("page", 1)))
        page_size = max(1, min(200, int(request.args.get("page_size", 20))))
        file_type = str(request.args.get("file_type", "") or "").strip()
        keyword = str(request.args.get("keyword", "") or "").strip()
        domain = _query_domain()

        records, total = service.list_files(
            file_type=file_type or None,
            keyword=keyword or None,
            domain=domain,
            page=page,
            page_size=page_size,
        )

        return jsonify(
            {
                "success": True,
                "page": page,
                "page_size": page_size,
                "total": total,
                "items": records,
            }
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error("获取统一文件列表失败: %s", e, exc_info=True)
        return jsonify({"error": f"获取统一文件列表失败: {str(e)}"}), 500


@files_bp.route("/files", methods=["DELETE"])
def delete_files():
    try:
        service = _file_storage_service()
        file_ids = _request_value("file_ids") or _request_value("ids") or []
        if isinstance(file_ids, str):
            file_ids = [item.strip() for item in file_ids.split(",") if item.strip()]
        if not isinstance(file_ids, list):
            return jsonify({"error": "file_ids 必须是数组"}), 400

        result = service.delete_files(file_ids)
        status_code = 200 if result.get("failed_count", 0) == 0 else 207
        return jsonify(result), status_code
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except FileStorageError as e:
        current_app.logger.error("统一文件批量删除失败: %s", e)
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        current_app.logger.error("统一文件批量删除失败: %s", e, exc_info=True)
        return jsonify({"error": f"统一文件批量删除失败: {str(e)}"}), 500


@files_bp.route("/files/<file_id>", methods=["GET"])
def read_file_by_id(file_id: str):
    try:
        service = _file_storage_service()
        meta_only = _to_bool(request.args.get("meta_only"), default=False)

        record = service.get_record(file_id)
        if not record:
            return jsonify({"error": FILE_NOT_FOUND_MESSAGE}), 404
        if meta_only:
            return jsonify({"success": True, "record": record.to_dict()})

        local_path = service.resolve_local_path(file_id)
        if local_path and os.path.isfile(local_path):
            mimetype, _ = mimetypes.guess_type(record.original_filename)
            return send_file(
                local_path,
                mimetype=mimetype or "application/octet-stream",
                as_attachment=False,
                conditional=True,
                download_name=record.original_filename,
            )

        record, data = service.read_file_by_id(file_id)
        mimetype, _ = mimetypes.guess_type(record.original_filename)
        return send_file(
            io.BytesIO(data),
            mimetype=mimetype or "application/octet-stream",
            as_attachment=False,
            conditional=True,
            download_name=record.original_filename,
        )
    except FileRecordNotFoundError:
        return jsonify({"error": FILE_NOT_FOUND_MESSAGE}), 404
    except FileBlobMissingError:
        current_app.logger.error("统一文件读取失败: file_id=%s, %s", file_id, FILE_BLOB_MISSING_MESSAGE)
        return jsonify({"error": FILE_BLOB_MISSING_MESSAGE}), 404
    except Exception as e:
        current_app.logger.error("按ID读取统一文件失败: %s", e, exc_info=True)
        return jsonify({"error": f"按ID读取统一文件失败: {str(e)}"}), 500


@files_bp.route("/files/by-filename", methods=["GET"])
def read_file_by_filename():
    try:
        service = _file_storage_service()
        filename = str(request.args.get("filename", "") or "").strip()
        if not filename:
            return jsonify({"error": "缺少filename参数"}), 400

        domain = _query_domain()
        meta_only = _to_bool(request.args.get("meta_only"), default=False)
        record = service.get_latest_record_by_filename(filename=filename, domain=domain)
        if not record:
            return jsonify({"error": FILE_NOT_FOUND_MESSAGE}), 404

        if meta_only:
            return jsonify({"success": True, "record": record.to_dict()})

        local_path = service.resolve_local_path(record.file_id)
        if local_path and os.path.isfile(local_path):
            mimetype, _ = mimetypes.guess_type(record.original_filename)
            return send_file(
                local_path,
                mimetype=mimetype or "application/octet-stream",
                as_attachment=False,
                conditional=True,
                download_name=record.original_filename,
            )

        _, data = service.read_file_by_filename(filename=filename, domain=domain)
        mimetype, _ = mimetypes.guess_type(record.original_filename)
        return send_file(
            io.BytesIO(data),
            mimetype=mimetype or "application/octet-stream",
            as_attachment=False,
            conditional=True,
            download_name=record.original_filename,
        )
    except FileRecordNotFoundError:
        return jsonify({"error": FILE_NOT_FOUND_MESSAGE}), 404
    except FileBlobMissingError:
        current_app.logger.error("按文件名读取统一文件失败: %s", FILE_BLOB_MISSING_MESSAGE)
        return jsonify({"error": FILE_BLOB_MISSING_MESSAGE}), 404
    except Exception as e:
        current_app.logger.error("按文件名读取统一文件失败: %s", e, exc_info=True)
        return jsonify({"error": f"按文件名读取统一文件失败: {str(e)}"}), 500


@files_bp.route("/files/<file_id>", methods=["DELETE"])
def delete_file(file_id: str):
    try:
        service = _file_storage_service()
        result = service.delete_file(file_id)
        return jsonify(result)
    except FileRecordNotFoundError:
        return jsonify({"error": FILE_NOT_FOUND_MESSAGE}), 404
    except FileBlobMissingError:
        current_app.logger.error("统一文件删除失败: file_id=%s, %s", file_id, FILE_BLOB_MISSING_MESSAGE)
        return jsonify({"error": FILE_BLOB_MISSING_MESSAGE}), 409
    except FileStorageError as e:
        current_app.logger.error("统一文件删除失败: file_id=%s err=%s", file_id, e)
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        current_app.logger.error("统一文件删除失败: %s", e, exc_info=True)
        return jsonify({"error": f"统一文件删除失败: {str(e)}"}), 500
