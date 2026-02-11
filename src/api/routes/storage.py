import os
import tempfile
from typing import Any, Dict, List

from flask import Blueprint, current_app, jsonify, request

from src.api.services.rag_service import RAGService
from src.ingestion.splitters.audit_issue_chunker import AuditIssueChunker
from src.ingestion.splitters.audit_report_chunker import AuditReportChunker
from src.ingestion.splitters.document_chunker import DocumentChunker
from src.ingestion.splitters.law_document_chunker import LawDocumentChunker
from src.ingestion.splitters.smart_chunker import SmartChunker


storage_bp = Blueprint('storage', __name__)


@storage_bp.route('/store', methods=['POST'])
def store_documents():
    try:
        is_json_request = request.is_json
        chunker_type = 'smart'

        if is_json_request:
            data = request.get_json()
            chunker_type = data.get('chunker_type') or data.get('chunker-type') or 'smart'
            if chunker_type == 'law':
                chunker_type = 'regulation'
            if chunker_type == 'audit':
                chunker_type = 'audit_report'
            if chunker_type == 'issue':
                chunker_type = 'audit_issue'
        elif request.form:
            chunker_type = request.form.get('chunker_type') or request.form.get('chunker-type') or 'smart'
            if chunker_type == 'law':
                chunker_type = 'regulation'
            if chunker_type == 'audit':
                chunker_type = 'audit_report'
            if chunker_type == 'issue':
                chunker_type = 'audit_issue'

        service: RAGService = current_app.extensions['rag_service']
        rag_processor = service.get_processor(chunker_type=chunker_type)

        if not is_json_request:
            return jsonify({"error": "请求必须是JSON格式"}), 400

        data = request.get_json()
        if 'documents' not in data:
            return jsonify({"error": "缺少documents字段"}), 400

        documents = data['documents']
        if not isinstance(documents, list):
            return jsonify({"error": "documents必须是一个文档列表"}), 400

        save_after_processing = data.get('save_after_processing', True)
        store_path = data.get('store_path')

        if store_path:
            rag_processor.vector_store_path = store_path

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
    except Exception as e:
        current_app.logger.error("存储文档时出错: %s", e)
        return jsonify({"error": f"存储文档失败: {str(e)}"}), 500


@storage_bp.route('/clear', methods=['POST'])
def clear_vector_store():
    try:
        service: RAGService = current_app.extensions['rag_service']
        rag_processor = service.get_processor()

        store_path = None
        if request.is_json:
            data = request.get_json()
            if data:
                store_path = data.get('store_path')

        if store_path:
            rag_processor.vector_store_path = store_path

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
    except Exception as e:
        current_app.logger.error("清空向量库时出错: %s", e)
        return jsonify({"error": f"清空向量库失败: {str(e)}"}), 500


@storage_bp.route('/upload_store', methods=['POST'])
def upload_and_store_documents():
    try:
        chunker_type = request.form.get('chunker_type') or request.form.get('chunker-type') or 'smart'
        if chunker_type == 'law':
            chunker_type = 'regulation'
        if chunker_type == 'audit':
            chunker_type = 'audit_report'
        if chunker_type == 'issue':
            chunker_type = 'audit_issue'

        service: RAGService = current_app.extensions['rag_service']
        rag_processor = service.get_processor(chunker_type=chunker_type)

        if 'files' not in request.files:
            return jsonify({"error": "没有上传文件"}), 400

        uploaded_files = request.files.getlist('files')
        if not uploaded_files or all(f.filename == '' for f in uploaded_files):
            return jsonify({"error": "没有选择任何文件"}), 400

        save_after_processing = request.form.get('save_after_processing', 'true').lower() == 'true'
        store_path = request.form.get('store_path')
        if store_path:
            rag_processor.vector_store_path = store_path

        temp_file_paths: List[str] = []
        original_filenames: List[str] = []

        for file in uploaded_files:
            if file and file.filename:
                filename = file.filename.replace('/', '_').replace('\\', '_').replace('\x00', '')
                original_filenames.append(filename)
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1])
                file.save(temp_file.name)
                temp_file_paths.append(temp_file.name)

        doc_type = request.form.get('doc_type', 'internal_regulation')
        title = request.form.get('title', None)

        num_processed = rag_processor.process_documents_from_files(
            temp_file_paths,
            save_after_processing=save_after_processing,
            doc_type=doc_type,
            title=title,
            original_filenames=original_filenames,
        )

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
                "chunker_used": chunker_type,
            })

        return jsonify({
            "success": True,
            "message": f"成功处理了 {len(uploaded_files)} 个文件，生成了 {num_processed} 个文本块",
            "file_count": len(uploaded_files),
            "processed_count": num_processed,
            "chunker_used": chunker_type,
        })
    except Exception as e:
        current_app.logger.error("上传并存储文档时出错: %s", e)
        return jsonify({"error": f"上传并存储文档失败: {str(e)}"}), 500


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

        if chunker_type == 'law':
            chunker_type = 'regulation'
        if chunker_type == 'audit':
            chunker_type = 'audit_report'
        if chunker_type == 'issue':
            chunker_type = 'audit_issue'

        if not doc_type:
            if chunker_type == 'regulation':
                doc_type = 'internal_regulation'
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
        elif chunker_type in ('audit_report', 'audit'):
            chunker = AuditReportChunker(chunk_size=chunk_size, overlap=overlap)
        elif chunker_type in ('audit_issue', 'issue'):
            chunker = AuditIssueChunker(chunk_size=chunk_size, overlap=overlap)
        elif chunker_type == 'smart':
            chunker = SmartChunker(chunk_size=chunk_size, overlap=overlap)
        else:
            chunker = DocumentChunker(chunk_size=chunk_size, overlap=overlap)

        chunks = chunker.chunk_documents([temp_document])
        formatted_chunks = []
        for i, chunk in enumerate(chunks):
            formatted_chunks.append({
                "chunk_id": i + 1,
                "text": chunk['text'],
                "full_text_length": len(chunk['text']),
                "semantic_boundary": chunk.get('semantic_boundary', 'content'),
                "section_path": chunk.get('section_path', []),
                "header": chunk.get('header', ''),
                "char_count": chunk.get('char_count', len(chunk['text'])),
            })

        return jsonify({
            "success": True,
            "chunker_used": chunker_type,
            "original_text_length": len(text),
            "chunks_count": len(chunks),
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

        if chunker_type == 'law':
            chunker_type = 'regulation'
        if chunker_type == 'audit':
            chunker_type = 'audit_report'
        if chunker_type == 'issue':
            chunker_type = 'audit_issue'

        if not doc_type:
            if chunker_type == 'regulation':
                doc_type = 'internal_regulation'
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
            from src.ingestion.parsers.document_processor import process_uploaded_documents

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
            elif chunker_type in ('audit_report', 'audit'):
                chunker = AuditReportChunker(chunk_size=chunk_size, overlap=overlap)
            elif chunker_type in ('audit_issue', 'issue'):
                chunker = AuditIssueChunker(chunk_size=chunk_size, overlap=overlap)
            elif chunker_type == 'smart':
                chunker = SmartChunker(chunk_size=chunk_size, overlap=overlap)
            else:
                chunker = DocumentChunker(chunk_size=chunk_size, overlap=overlap)

            chunks = chunker.chunk_documents([temp_document])
            formatted_chunks = []
            for i, chunk in enumerate(chunks):
                formatted_chunks.append({
                    "chunk_id": i + 1,
                    "text": chunk['text'],
                    "full_text_length": len(chunk['text']),
                    "semantic_boundary": chunk.get('semantic_boundary', 'content'),
                    "section_path": chunk.get('section_path', []),
                    "header": chunk.get('header', ''),
                    "char_count": chunk.get('char_count', len(chunk['text'])),
                })

            return jsonify({
                "success": True,
                "filename": filename,
                "file_type": doc['file_type'],
                "chunker_used": chunker_type,
                "original_text_length": len(text),
                "chunks_count": len(chunks),
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
