import json
import os
import re
import tempfile
from typing import Any, Dict, List

from flask import Blueprint, current_app, jsonify, request

from src.api.routes.scope_utils import extract_scope_from_request
from src.api.services.rag_service import RAGService
from src.ingestion.parsers.archive_processor import (
    ArchiveValidationError,
    extract_zip_archive,
)
from src.ingestion.parsers.document_processor import process_uploaded_documents
from src.ingestion.splitters.audit_issue_chunker import AuditIssueChunker
from src.ingestion.splitters.audit_report_chunker import AuditReportChunker
from src.ingestion.splitters.case_material_chunker import CaseMaterialChunker
from src.ingestion.splitters.document_chunker import DocumentChunker
from src.ingestion.splitters.law_document_chunker import LawDocumentChunker
from src.ingestion.splitters.speech_material_chunker import SpeechMaterialChunker
from src.ingestion.splitters.technical_standard_chunker import TechnicalStandardChunker
from src.ingestion.splitters.smart_chunker import SmartChunker


storage_bp = Blueprint('storage', __name__)

ALLOWED_UPLOAD_EXTENSIONS = {'.pdf', '.docx', '.txt'}
MAX_ARCHIVE_UPLOAD_BYTES = 200 * 1024 * 1024
MAX_ARCHIVE_FILE_COUNT = 500
MAX_ARCHIVE_SINGLE_FILE_BYTES = 30 * 1024 * 1024
MAX_ARCHIVE_TOTAL_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_COMPRESSION_RATIO = 200.0


def _to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'y', 'on')
    return default


def _parse_json_object_field(raw_value: Any, field_name: str) -> Dict[str, Any]:
    if raw_value in (None, ""):
        return {}
    if isinstance(raw_value, dict):
        return dict(raw_value)
    try:
        parsed = json.loads(str(raw_value))
    except (TypeError, ValueError, json.JSONDecodeError):
        raise ValueError(f"{field_name} 必须是合法的 JSON 对象")
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_name} 必须是 JSON 对象")
    return parsed


def _normalize_chunker_type(value: str) -> str:
    chunker_type = value or 'smart'
    if chunker_type == 'law':
        return 'regulation'
    if chunker_type in {'technical', 'tech_standard', 'standard'}:
        return 'technical_standard'
    if chunker_type in {'speech', 'speech_report', 'important_speech'}:
        return 'speech_material'
    if chunker_type in {'case', 'case_report', 'case_library'}:
        return 'case_material'
    if chunker_type == 'audit':
        return 'audit_report'
    if chunker_type == 'issue':
        return 'audit_issue'
    return chunker_type


def _ensure_no_custom_store_path(store_path: Any) -> None:
    if str(store_path or "").strip():
        raise ValueError("多知识域模式下不支持自定义store_path，请改用scope参数")


def _get_scoped_processor(service: RAGService, chunker_type: str = None, json_data: Dict[str, Any] = None):
    scope = extract_scope_from_request(request, json_data=json_data)
    return service.get_processor(scope=scope, chunker_type=chunker_type)


def _is_regulation_doc_type(doc_type: str) -> bool:
    normalized = str(doc_type or "").strip().lower()
    return normalized in {"internal_regulation", "external_regulation"}


def _resolve_upload_doc_type(scope: str, knowledge_labels: Dict[str, List[str]], requested_doc_type: str = None) -> str:
    if str(scope or "").strip().lower() != "discipline":
        return str(requested_doc_type or "internal_regulation").strip() or "internal_regulation"

    library_values = knowledge_labels.get("library") or []
    library = str(library_values[0] if library_values else "").strip()
    library_doc_type_map = {
        "important_speeches": "internal_report",
        "case_library": "internal_report",
        "national_laws": "internal_regulation",
        "party_regulations": "internal_regulation",
    }
    return library_doc_type_map.get(library, "internal_regulation")


def _infer_catalog_level(semantic_boundary: str, header: str, section_path: List[str]) -> int:
    boundary = str(semantic_boundary or '').lower()
    normalized_header = str(header or '').strip()

    if boundary == 'chapter':
        return 1
    if boundary == 'section':
        return 2
    if boundary == 'article':
        return 3

    if normalized_header.startswith('第') and '章' in normalized_header:
        return 1
    if normalized_header.startswith('第') and '节' in normalized_header:
        return 2
    if normalized_header.startswith('第') and '条' in normalized_header:
        return 3

    return max(1, min(6, len(section_path) + 1))


def _infer_catalog_node_type(semantic_boundary: str, header: str) -> str:
    boundary = str(semantic_boundary or '').strip().lower()
    normalized_header = str(header or '').strip()

    if boundary in {'chapter', 'section', 'article', 'content'}:
        return boundary
    if normalized_header.startswith('第') and '章' in normalized_header:
        return 'chapter'
    if normalized_header.startswith('第') and '节' in normalized_header:
        return 'section'
    if normalized_header.startswith('第') and '条' in normalized_header:
        return 'article'
    return 'content'


def _build_catalog_display_title(node_type: str, title: str) -> str:
    normalized_title = str(title or '').strip()
    if not normalized_title:
        return ''
    if node_type == 'article':
        match = re.search(r'(第[一二三四五六七八九十百千万零〇两\d]+条)', normalized_title)
        if match:
            return match.group(1).strip()
    return normalized_title


def _build_catalog_preview_text(text: str, section_path: List[str], title: str, display_title: str, node_type: str) -> str:
    if node_type != 'article':
        return ''

    cleaned = re.sub(r'\[\[PAGE:\d+\]\]', ' ', str(text or ''))
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if not cleaned:
        return ''

    for prefix in [*section_path, title, display_title]:
        normalized_prefix = str(prefix or '').strip()
        if normalized_prefix and cleaned.startswith(normalized_prefix):
            cleaned = cleaned[len(normalized_prefix):].lstrip('：:，,。；;、-— \t')

    return cleaned[:120].strip()


def _format_chunks_with_catalog(chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
    formatted_chunks: List[Dict[str, Any]] = []
    catalog: List[Dict[str, Any]] = []
    full_text_lines: List[str] = []
    seen_catalog_keys = set()
    next_line_no = 1

    for i, chunk in enumerate(chunks):
        text = str(chunk.get('text', '') or '')
        lines = text.splitlines() or ['']
        line_start = next_line_no
        line_end = next_line_no + len(lines) - 1
        full_text_lines.extend(lines)

        section_path = [str(item).strip() for item in (chunk.get('section_path', []) or []) if str(item).strip()]
        header = str(chunk.get('header', '') or '').strip()

        if header:
            catalog_path = section_path.copy()
            if not catalog_path or catalog_path[-1] != header:
                catalog_path.append(header)

            catalog_key = tuple(catalog_path) if catalog_path else (header,)
            if catalog_key not in seen_catalog_keys:
                seen_catalog_keys.add(catalog_key)
                node_type = _infer_catalog_node_type(chunk.get('semantic_boundary', ''), header)
                display_title = _build_catalog_display_title(node_type, header)
                preview_text = _build_catalog_preview_text(text, catalog_path, header, display_title, node_type)
                anchor_line = line_start
                for offset, line in enumerate(lines):
                    normalized_line = line.strip()
                    if normalized_line and normalized_line.startswith(header):
                        anchor_line = line_start + offset
                        break

                catalog.append({
                    'id': f'catalog_{len(catalog) + 1}',
                    'title': header,
                    'display_title': display_title,
                    'preview_text': preview_text,
                    'node_type': node_type,
                    'level': _infer_catalog_level(chunk.get('semantic_boundary', ''), header, section_path),
                    'line_no': anchor_line,
                    'chunk_id': i + 1,
                    'section_path': catalog_path,
                })

        formatted_chunks.append({
            'chunk_id': i + 1,
            'text': text,
            'full_text_length': len(text),
            'semantic_boundary': chunk.get('semantic_boundary', 'content'),
            'section_path': chunk.get('section_path', []),
            'header': chunk.get('header', ''),
            'char_count': chunk.get('char_count', len(text)),
            'line_start': line_start,
            'line_end': line_end,
        })
        next_line_no = line_end + 1

    return {
        'formatted_chunks': formatted_chunks,
        'catalog': catalog,
        'full_text_lines': full_text_lines,
    }


@storage_bp.route('/store', methods=['POST'])
def store_documents():
    try:
        is_json_request = request.is_json
        chunker_type = 'smart'

        if is_json_request:
            data = request.get_json()
            chunker_type = _normalize_chunker_type(
                data.get('chunker_type') or data.get('chunker-type') or 'smart'
            )
        elif request.form:
            chunker_type = _normalize_chunker_type(
                request.form.get('chunker_type') or request.form.get('chunker-type') or 'smart'
            )

        if not is_json_request:
            return jsonify({"error": "请求必须是JSON格式"}), 400

        data = request.get_json(silent=True) or {}
        service: RAGService = current_app.extensions['rag_service']
        rag_processor = _get_scoped_processor(service, chunker_type=chunker_type, json_data=data)
        if 'documents' not in data:
            return jsonify({"error": "缺少documents字段"}), 400

        documents = data['documents']
        if not isinstance(documents, list):
            return jsonify({"error": "documents必须是一个文档列表"}), 400

        save_after_processing = data.get('save_after_processing', True)
        _ensure_no_custom_store_path(data.get('store_path'))

        num_processed = rag_processor.process_documents(documents, save_after_processing=save_after_processing)

        if isinstance(num_processed, dict):
            return jsonify({
                "success": True,
                "message": f"处理完成: 新增 {num_processed.get('processed', 0)} 个, 跳过 {num_processed.get('skipped', 0)} 个重复, 更新 {num_processed.get('updated', 0)} 个",
                "processed_count": num_processed.get('processed', 0),
                "skipped_count": num_processed.get('skipped', 0),
                "updated_count": num_processed.get('updated', 0),
                "total_chunks": num_processed.get('total_chunks', 0),
                "chunker_used": chunker_type,
            })

        return jsonify({
            "success": True,
            "message": f"成功处理了 {num_processed} 个文本块",
            "processed_count": num_processed,
            "chunker_used": chunker_type
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error("存储文档时出错: %s", e)
        return jsonify({"error": f"存储文档失败: {str(e)}"}), 500


@storage_bp.route('/clear', methods=['POST'])
def clear_vector_store():
    try:
        service: RAGService = current_app.extensions['rag_service']
        data = request.get_json(silent=True) if request.is_json else {}
        _ensure_no_custom_store_path((data or {}).get('store_path'))
        rag_processor = _get_scoped_processor(service, json_data=data)

        rag_processor.clear_vector_store()

        try:
            rag_processor.save_vector_store()
        except ValueError as ve:
            if "没有可保存的向量库" in str(ve):
                from src.indexing.vector.vector_store import VectorStore
                rag_processor.vector_store = VectorStore(dimension=rag_processor.dimension or 1024)
                rag_processor.save_vector_store()
            else:
                raise

        return jsonify({
            "success": True,
            "message": "向量库已清空并保存"
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error("清空向量库时出错: %s", e)
        return jsonify({"error": f"清空向量库失败: {str(e)}"}), 500


@storage_bp.route('/graph/rebuild', methods=['POST'])
def rebuild_graph_index():
    try:
        service: RAGService = current_app.extensions['rag_service']
        rag_processor = _get_scoped_processor(service)

        rag_processor.load_vector_store()
        stats = rag_processor.rebuild_graph_index(save=True)

        return jsonify({
            "success": True,
            "message": "图索引重建完成",
            "graph_stats": stats,
            "graph_info": rag_processor.get_graph_stats(),
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error("重建图索引失败: %s", e)
        return jsonify({"error": f"重建图索引失败: {str(e)}"}), 500


@storage_bp.route('/graph/nodes', methods=['GET'])
def list_graph_nodes():
    try:
        service: RAGService = current_app.extensions['rag_service']
        rag_processor = _get_scoped_processor(service)

        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 20))
        node_type = request.args.get('node_type')
        keyword = request.args.get('keyword')
        include_evidence_nodes = _to_bool(request.args.get('include_evidence_nodes'), default=False)

        page = max(1, page)
        page_size = max(1, min(200, page_size))

        data = rag_processor.list_graph_nodes(
            page=page,
            page_size=page_size,
            node_type=node_type,
            keyword=keyword,
            include_evidence_nodes=include_evidence_nodes,
        )
        return jsonify({"success": True, **data})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error("获取图节点失败: %s", e)
        return jsonify({"error": f"获取图节点失败: {str(e)}"}), 500


@storage_bp.route('/graph/edges', methods=['GET'])
def list_graph_edges():
    try:
        service: RAGService = current_app.extensions['rag_service']
        rag_processor = _get_scoped_processor(service)

        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 20))
        relation = request.args.get('relation')
        keyword = request.args.get('keyword')
        include_evidence_nodes = _to_bool(request.args.get('include_evidence_nodes'), default=False)

        page = max(1, page)
        page_size = max(1, min(200, page_size))

        data = rag_processor.list_graph_edges(
            page=page,
            page_size=page_size,
            relation=relation,
            keyword=keyword,
            include_evidence_nodes=include_evidence_nodes,
        )
        return jsonify({"success": True, **data})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error("获取图边失败: %s", e)
        return jsonify({"error": f"获取图边失败: {str(e)}"}), 500


@storage_bp.route('/graph/subgraph', methods=['POST'])
def get_graph_subgraph():
    try:
        data = request.get_json(silent=True) or {}
        service: RAGService = current_app.extensions['rag_service']
        rag_processor = _get_scoped_processor(service, json_data=data)
        query = data.get('query')
        node_ids = data.get('node_ids') if isinstance(data.get('node_ids'), list) else []
        hops = int(data.get('hops', 2))
        max_nodes = int(data.get('max_nodes', 120))
        include_evidence_nodes = _to_bool(data.get('include_evidence_nodes'), default=False)

        result = rag_processor.get_graph_subgraph(
            query=query,
            node_ids=node_ids,
            hops=hops,
            max_nodes=max_nodes,
            include_evidence_nodes=include_evidence_nodes,
        )
        return jsonify({"success": True, **result})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error("获取子图失败: %s", e)
        return jsonify({"error": f"获取子图失败: {str(e)}"}), 500


@storage_bp.route('/graph/path', methods=['POST'])
def get_graph_path():
    try:
        data = request.get_json(silent=True) or {}
        service: RAGService = current_app.extensions['rag_service']
        rag_processor = _get_scoped_processor(service, json_data=data)
        source_node_id = str(data.get('source_node_id', '') or '')
        target_node_id = str(data.get('target_node_id', '') or '')
        source_query = str(data.get('source_query', '') or '')
        target_query = str(data.get('target_query', '') or '')
        include_evidence_nodes = _to_bool(data.get('include_evidence_nodes'), default=False)
        try:
            max_hops = int(data.get('max_hops', 4))
        except (TypeError, ValueError):
            max_hops = 4
        try:
            max_candidates = int(data.get('max_candidates', 5))
        except (TypeError, ValueError):
            max_candidates = 5

        max_hops = max(1, min(8, max_hops))
        max_candidates = max(1, min(10, max_candidates))

        result = rag_processor.get_graph_path(
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            source_query=source_query,
            target_query=target_query,
            max_hops=max_hops,
            max_candidates=max_candidates,
            include_evidence_nodes=include_evidence_nodes,
        )
        return jsonify({"success": True, **result})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error("获取图路径失败: %s", e)
        return jsonify({"error": f"获取图路径失败: {str(e)}"}), 500


@storage_bp.route('/graph/overview', methods=['GET'])
def get_graph_overview():
    try:
        service: RAGService = current_app.extensions['rag_service']
        rag_processor = _get_scoped_processor(service)

        top_n = int(request.args.get('top_n', 8))
        top_n = max(3, min(50, top_n))

        result = rag_processor.get_graph_overview(top_n=top_n)
        return jsonify({"success": True, **result})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error("获取图谱总览失败: %s", e)
        return jsonify({"error": f"获取图谱总览失败: {str(e)}"}), 500


@storage_bp.route('/graph/node/<node_id>', methods=['GET'])
def get_graph_node_detail(node_id: str):
    try:
        service: RAGService = current_app.extensions['rag_service']
        rag_processor = _get_scoped_processor(service)

        max_neighbors = int(request.args.get('max_neighbors', 120))
        max_neighbors = max(20, min(300, max_neighbors))

        result = rag_processor.get_graph_node_detail(node_id=node_id, max_neighbors=max_neighbors)
        if not result:
            return jsonify({"error": "节点不存在"}), 404

        return jsonify({"success": True, **result})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error("获取图节点详情失败: %s", e)
        return jsonify({"error": f"获取图节点详情失败: {str(e)}"}), 500


@storage_bp.route('/upload_store', methods=['POST'])
def upload_and_store_documents():
    try:
        chunker_type = _normalize_chunker_type(
            request.form.get('chunker_type') or request.form.get('chunker-type') or 'smart'
        )

        service: RAGService = current_app.extensions['rag_service']
        rag_processor = _get_scoped_processor(service, chunker_type=chunker_type)

        if 'files' not in request.files:
            return jsonify({"error": "没有上传文件"}), 400

        uploaded_files = request.files.getlist('files')
        if not uploaded_files or all(f.filename == '' for f in uploaded_files):
            return jsonify({"error": "没有选择任何文件"}), 400

        file_storage_service = current_app.extensions.get('file_storage_service')
        if not file_storage_service:
            return jsonify({"error": "统一文件存储服务未初始化"}), 503

        save_after_processing = request.form.get('save_after_processing', 'true').lower() == 'true'
        searchable = _to_bool(request.form.get('searchable', 'true'), default=True)
        _ensure_no_custom_store_path(request.form.get('store_path'))
        knowledge_labels = service.normalize_scope_knowledge_labels(
            rag_processor.scope,
            _parse_json_object_field(request.form.get('knowledge_labels'), 'knowledge_labels'),
            require_required_fields=True,
        )

        temp_file_paths: List[str] = []
        file_id_by_temp_path: Dict[str, str] = {}
        original_filenames: List[str] = []
        parse_errors: List[Dict[str, str]] = []

        try:
            for file in uploaded_files:
                if file and file.filename:
                    filename = file.filename.replace('/', '_').replace('\\', '_').replace('\x00', '')
                    original_filenames.append(filename)
                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1])
                    file.save(temp_file.name)
                    temp_file_paths.append(temp_file.name)
                    stored = file_storage_service.store_from_path(
                        source_path=temp_file.name,
                        original_filename=filename,
                        domain=rag_processor.scope,
                    )
                    file_id_by_temp_path[temp_file.name] = stored.file_id

            doc_type = _resolve_upload_doc_type(
                rag_processor.scope,
                knowledge_labels,
                request.form.get('doc_type'),
            )
            enable_regulation_group = _to_bool(request.form.get('enable_regulation_group', 'false'), default=False)
            regulation_group_id = str(request.form.get('regulation_group_id', '') or '').strip()
            regulation_group_name = str(request.form.get('regulation_group_name', '') or '').strip()
            version_label = str(request.form.get('version_label', '') or '').strip()
            if enable_regulation_group and not _is_regulation_doc_type(doc_type):
                return jsonify({"error": "只有制度类文档支持版本分组"}), 400

            title = request.form.get('title', None)
            extra_metadata = {
                "searchable": searchable,
                "enable_regulation_group": enable_regulation_group,
                "regulation_group_id": regulation_group_id,
                "regulation_group_name": regulation_group_name,
                "version_label": version_label,
                "knowledge_labels": knowledge_labels,
            }

            documents = process_uploaded_documents(
                temp_file_paths,
                doc_type=doc_type,
                title=title,
                original_filenames=original_filenames,
                error_collector=parse_errors,
                extra_metadata=extra_metadata,
            )
            for doc in documents:
                mapped_file_id = file_id_by_temp_path.get(str(doc.get("file_path", "") or ""))
                if mapped_file_id:
                    doc["storage_file_id"] = mapped_file_id
            if not documents:
                return jsonify({
                    "error": "上传文件解析后没有可入库文档",
                    "file_count": len(uploaded_files),
                    "failed_files": parse_errors,
                }), 400

            num_processed = rag_processor.process_documents(
                documents,
                save_after_processing=save_after_processing,
            )
        finally:
            for temp_path in temp_file_paths:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

        if isinstance(num_processed, dict):
            return jsonify({
                "success": True,
                "message": f"处理完成: 新增 {num_processed.get('processed', 0)} 个, 跳过 {num_processed.get('skipped', 0)} 个重复, 更新 {num_processed.get('updated', 0)} 个",
                "file_count": len(uploaded_files),
                "processed_count": num_processed.get('processed', 0),
                "skipped_count": num_processed.get('skipped', 0),
                "updated_count": num_processed.get('updated', 0),
                "total_chunks": num_processed.get('total_chunks', 0),
                "failed_files": parse_errors,
                "chunker_used": chunker_type,
            })

        return jsonify({
            "success": True,
            "message": f"成功处理了 {len(uploaded_files)} 个文件，生成了 {num_processed} 个文本块",
            "file_count": len(uploaded_files),
            "processed_count": num_processed,
            "failed_files": parse_errors,
            "chunker_used": chunker_type,
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error("上传并存储文档时出错: %s", e)
        return jsonify({"error": f"上传并存储文档失败: {str(e)}"}), 500


@storage_bp.route('/upload_archive_store', methods=['POST'])
def upload_archive_and_store_documents():
    temp_archive_path = None
    try:
        chunker_type = _normalize_chunker_type(
            request.form.get('chunker_type') or request.form.get('chunker-type') or 'smart'
        )

        service: RAGService = current_app.extensions['rag_service']
        rag_processor = _get_scoped_processor(service, chunker_type=chunker_type)

        uploaded_archive = request.files.get('archive')
        if not uploaded_archive or not uploaded_archive.filename:
            return jsonify({"error": "没有上传压缩包文件"}), 400

        archive_name = uploaded_archive.filename.replace('/', '_').replace('\\', '_').replace('\x00', '')
        if os.path.splitext(archive_name)[1].lower() != '.zip':
            return jsonify({"error": "仅支持上传 ZIP 压缩包"}), 400

        file_storage_service = current_app.extensions.get('file_storage_service')
        if not file_storage_service:
            return jsonify({"error": "统一文件存储服务未初始化"}), 503

        save_after_processing = _to_bool(request.form.get('save_after_processing', 'true'), default=True)
        searchable = _to_bool(request.form.get('searchable', 'true'), default=True)
        _ensure_no_custom_store_path(request.form.get('store_path'))
        knowledge_labels = service.normalize_scope_knowledge_labels(
            rag_processor.scope,
            _parse_json_object_field(request.form.get('knowledge_labels'), 'knowledge_labels'),
            require_required_fields=True,
        )

        doc_type = _resolve_upload_doc_type(
            rag_processor.scope,
            knowledge_labels,
            request.form.get('doc_type'),
        )
        enable_regulation_group = _to_bool(request.form.get('enable_regulation_group', 'false'), default=False)
        regulation_group_id = str(request.form.get('regulation_group_id', '') or '').strip()
        regulation_group_name = str(request.form.get('regulation_group_name', '') or '').strip()
        version_label = str(request.form.get('version_label', '') or '').strip()
        if enable_regulation_group and not _is_regulation_doc_type(doc_type):
            return jsonify({"error": "只有制度类文档支持版本分组"}), 400
        title = request.form.get('title', None)
        extra_metadata = {
            "searchable": searchable,
            "enable_regulation_group": enable_regulation_group,
            "regulation_group_id": regulation_group_id,
            "regulation_group_name": regulation_group_name,
            "version_label": version_label,
            "knowledge_labels": knowledge_labels,
        }

        temp_archive = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
        temp_archive_path = temp_archive.name
        temp_archive.close()
        uploaded_archive.save(temp_archive_path)

        archive_size = os.path.getsize(temp_archive_path)
        if archive_size > MAX_ARCHIVE_UPLOAD_BYTES:
            return jsonify({"error": f"压缩包过大，超过限制 {MAX_ARCHIVE_UPLOAD_BYTES} bytes"}), 400

        parse_errors: List[Dict[str, str]] = []
        with tempfile.TemporaryDirectory() as extract_dir:
            extraction = extract_zip_archive(
                archive_path=temp_archive_path,
                output_dir=extract_dir,
                allowed_extensions=ALLOWED_UPLOAD_EXTENSIONS,
                max_file_count=MAX_ARCHIVE_FILE_COUNT,
                max_single_file_bytes=MAX_ARCHIVE_SINGLE_FILE_BYTES,
                max_total_uncompressed_bytes=MAX_ARCHIVE_TOTAL_UNCOMPRESSED_BYTES,
                max_compression_ratio=MAX_ARCHIVE_COMPRESSION_RATIO,
            )

            file_id_by_path: Dict[str, str] = {}
            for idx, extracted_path in enumerate(extraction.extracted_paths):
                original_name = extraction.original_filenames[idx] if idx < len(extraction.original_filenames) else os.path.basename(extracted_path)
                stored = file_storage_service.store_from_path(
                    source_path=extracted_path,
                    original_filename=original_name,
                    domain=rag_processor.scope,
                )
                file_id_by_path[extracted_path] = stored.file_id

            documents = process_uploaded_documents(
                extraction.extracted_paths,
                doc_type=doc_type,
                title=title,
                original_filenames=extraction.original_filenames,
                error_collector=parse_errors,
                extra_metadata=extra_metadata,
            )
            for doc in documents:
                mapped_file_id = file_id_by_path.get(str(doc.get("file_path", "") or ""))
                if mapped_file_id:
                    doc["storage_file_id"] = mapped_file_id
            if not documents:
                return jsonify({
                    "error": "压缩包解析后没有可入库文档",
                    "archive_name": archive_name,
                    "extracted_count": extraction.extracted_count,
                    "unsupported_files": extraction.unsupported_files,
                    "failed_files": parse_errors,
                }), 400

            num_processed = rag_processor.process_documents(
                documents,
                save_after_processing=save_after_processing,
            )

        if isinstance(num_processed, dict):
            return jsonify({
                "success": True,
                "message": f"处理完成: 新增 {num_processed.get('processed', 0)} 个, 跳过 {num_processed.get('skipped', 0)} 个重复, 更新 {num_processed.get('updated', 0)} 个",
                "archive_name": archive_name,
                "file_count": extraction.extracted_count,
                "extracted_count": extraction.extracted_count,
                "unsupported_files": extraction.unsupported_files,
                "failed_files": parse_errors,
                "processed_count": num_processed.get('processed', 0),
                "skipped_count": num_processed.get('skipped', 0),
                "updated_count": num_processed.get('updated', 0),
                "total_chunks": num_processed.get('total_chunks', 0),
                "chunker_used": chunker_type,
            })

        return jsonify({
            "success": True,
            "message": f"成功处理了压缩包内 {num_processed} 个文本块",
            "archive_name": archive_name,
            "file_count": extraction.extracted_count,
            "extracted_count": extraction.extracted_count,
            "unsupported_files": extraction.unsupported_files,
            "failed_files": parse_errors,
            "processed_count": num_processed,
            "chunker_used": chunker_type,
        })
    except ArchiveValidationError as e:
        return jsonify({"error": str(e)}), 400
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error("上传压缩包并存储文档时出错: %s", e)
        return jsonify({"error": f"上传压缩包并存储文档失败: {str(e)}"}), 500
    finally:
        if temp_archive_path:
            try:
                os.unlink(temp_archive_path)
            except OSError:
                pass


@storage_bp.route('/chunk_test', methods=['POST'])
def test_chunking():
    try:
        if not request.is_json:
            return jsonify({"error": "请求必须是JSON格式"}), 400

        data = request.get_json()
        if 'text' not in data:
            return jsonify({"error": "缺少text字段"}), 400

        text = data['text']
        filename = data.get('filename', 'test_document.txt')
        chunker_type = data.get('chunker_type') or data.get('chunker-type') or 'smart'
        doc_type = data.get('doc_type')

        chunker_type = _normalize_chunker_type(chunker_type)

        if not doc_type:
            if chunker_type == 'regulation':
                doc_type = 'internal_regulation'
            elif chunker_type == 'technical_standard':
                doc_type = 'internal_regulation'
            elif chunker_type == 'speech_material':
                doc_type = 'internal_report'
            elif chunker_type == 'case_material':
                doc_type = 'internal_report'
            elif chunker_type == 'audit_report':
                doc_type = 'internal_report'
            elif chunker_type == 'audit_issue':
                doc_type = 'audit_issue'
            else:
                doc_type = 'internal_regulation'

        chunk_size = data.get('chunk_size', 512)
        overlap = data.get('overlap', 50)

        temp_document = {
            'doc_id': 'test_doc',
            'filename': filename,
            'file_type': 'txt',
            'text': text,
            'doc_type': doc_type,
            'char_count': len(text),
        }

        if chunker_type in ('regulation', 'law'):
            chunker = LawDocumentChunker(chunk_size=chunk_size, overlap=overlap)
        elif chunker_type == 'technical_standard':
            chunker = TechnicalStandardChunker(chunk_size=chunk_size, overlap=overlap)
        elif chunker_type == 'speech_material':
            chunker = SpeechMaterialChunker(chunk_size=chunk_size, overlap=overlap)
        elif chunker_type == 'case_material':
            chunker = CaseMaterialChunker(chunk_size=chunk_size, overlap=overlap)
        elif chunker_type in ('audit_report', 'audit'):
            chunker = AuditReportChunker(chunk_size=chunk_size, overlap=overlap)
        elif chunker_type in ('audit_issue', 'issue'):
            chunker = AuditIssueChunker(chunk_size=chunk_size, overlap=overlap)
        elif chunker_type == 'smart':
            chunker = SmartChunker(chunk_size=chunk_size, overlap=overlap)
        else:
            chunker = DocumentChunker(chunk_size=chunk_size, overlap=overlap)

        chunks = chunker.chunk_documents([temp_document])
        preview_payload = _format_chunks_with_catalog(chunks)
        formatted_chunks = preview_payload['formatted_chunks']

        return jsonify({
            "success": True,
            "chunker_used": chunker_type,
            "original_text_length": len(text),
            "chunks_count": len(chunks),
            "total_lines": len(preview_payload['full_text_lines']),
            "catalog": preview_payload['catalog'],
            "full_text_lines": preview_payload['full_text_lines'],
            "chunks": formatted_chunks,
        })
    except Exception as e:
        current_app.logger.error("测试分块时出错: %s", e)
        return jsonify({"error": f"测试分块失败: {str(e)}"}), 500


@storage_bp.route('/chunk_test_upload', methods=['POST'])
def test_chunking_upload():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "没有上传文件"}), 400

        uploaded_file = request.files['file']
        if not uploaded_file or uploaded_file.filename == '':
            return jsonify({"error": "没有选择文件"}), 400

        chunker_type = request.form.get('chunker_type') or request.form.get('chunker-type') or 'smart'
        doc_type = request.form.get('doc_type')

        chunker_type = _normalize_chunker_type(chunker_type)

        if not doc_type:
            if chunker_type == 'regulation':
                doc_type = 'internal_regulation'
            elif chunker_type == 'technical_standard':
                doc_type = 'internal_regulation'
            elif chunker_type == 'speech_material':
                doc_type = 'internal_report'
            elif chunker_type == 'case_material':
                doc_type = 'internal_report'
            elif chunker_type == 'audit_report':
                doc_type = 'internal_report'
            elif chunker_type == 'audit_issue':
                doc_type = 'audit_issue'
            else:
                doc_type = 'internal_regulation'

        chunk_size = int(request.form.get('chunk_size', 512))
        overlap = int(request.form.get('overlap', 50))

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.filename)[1])
        uploaded_file.save(temp_file.name)

        try:
            processed_docs = process_uploaded_documents([temp_file.name], doc_type=doc_type)
            if not processed_docs:
                return jsonify({"error": "无法处理上传的文件"}), 400

            doc = processed_docs[0]
            text = doc['text']
            filename = doc['filename']

            temp_document: Dict[str, Any] = {
                'doc_id': 'test_doc',
                'filename': filename,
                'file_type': doc['file_type'],
                'doc_type': doc.get('doc_type', doc_type),
                'text': text,
                'char_count': len(text),
            }

            if chunker_type in ('regulation', 'law'):
                chunker = LawDocumentChunker(chunk_size=chunk_size, overlap=overlap)
            elif chunker_type == 'technical_standard':
                chunker = TechnicalStandardChunker(chunk_size=chunk_size, overlap=overlap)
            elif chunker_type == 'speech_material':
                chunker = SpeechMaterialChunker(chunk_size=chunk_size, overlap=overlap)
            elif chunker_type == 'case_material':
                chunker = CaseMaterialChunker(chunk_size=chunk_size, overlap=overlap)
            elif chunker_type in ('audit_report', 'audit'):
                chunker = AuditReportChunker(chunk_size=chunk_size, overlap=overlap)
            elif chunker_type in ('audit_issue', 'issue'):
                chunker = AuditIssueChunker(chunk_size=chunk_size, overlap=overlap)
            elif chunker_type == 'smart':
                chunker = SmartChunker(chunk_size=chunk_size, overlap=overlap)
            else:
                chunker = DocumentChunker(chunk_size=chunk_size, overlap=overlap)

            chunks = chunker.chunk_documents([temp_document])
            preview_payload = _format_chunks_with_catalog(chunks)
            formatted_chunks = preview_payload['formatted_chunks']

            return jsonify({
                "success": True,
                "filename": filename,
                "file_type": doc['file_type'],
                "chunker_used": chunker_type,
                "original_text_length": len(text),
                "chunks_count": len(chunks),
                "total_lines": len(preview_payload['full_text_lines']),
                "catalog": preview_payload['catalog'],
                "full_text_lines": preview_payload['full_text_lines'],
                "chunks": formatted_chunks,
            })
        finally:
            try:
                os.unlink(temp_file.name)
            except OSError:
                pass
    except Exception as e:
        current_app.logger.error("上传并测试分块时出错: %s", e)
        return jsonify({"error": f"上传并测试分块失败: {str(e)}"}), 500
