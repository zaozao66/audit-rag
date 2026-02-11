import { useMemo, useState } from 'react';
import { clearAllDocuments, deleteDocument, getDocumentChunks, getDocumentDetail } from '../api/rag';
import type { DocumentChunksData, DocumentRecord } from '../types/rag';

interface DocumentsPanelProps {
  documents: DocumentRecord[];
  loading: boolean;
  docType: string;
  keyword: string;
  includeDeleted: boolean;
  onFilterChange: (next: { docType: string; keyword: string; includeDeleted: boolean }) => void;
  onRefresh: () => void;
  onDataChanged?: () => void;
}

export function DocumentsPanel({
  documents,
  loading,
  docType,
  keyword,
  includeDeleted,
  onFilterChange,
  onRefresh,
  onDataChanged
}: DocumentsPanelProps) {
  const [selectedId, setSelectedId] = useState('');
  const [chunkData, setChunkData] = useState<DocumentChunksData | null>(null);
  const [includeText, setIncludeText] = useState(false);
  const [error, setError] = useState('');
  const [working, setWorking] = useState(false);

  const selected = useMemo(() => documents.find((item) => item.doc_id === selectedId) ?? null, [documents, selectedId]);

  const loadDetail = async (docId: string) => {
    setSelectedId(docId);
    setError('');
    setWorking(true);
    try {
      await getDocumentDetail(docId);
      const chunks = await getDocumentChunks(docId, includeText);
      setChunkData(chunks.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载文档详情失败');
    } finally {
      setWorking(false);
    }
  };

  const removeDoc = async () => {
    if (!selectedId) return;
    if (!window.confirm(`确认删除文档 ${selectedId} ?`)) return;

    setWorking(true);
    setError('');
    try {
      await deleteDocument(selectedId);
      setChunkData(null);
      setSelectedId('');
      onRefresh();
      onDataChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败');
    } finally {
      setWorking(false);
    }
  };

  const removeAllDocs = async () => {
    if (!window.confirm('确认清空所有文档吗？该操作会真实删除向量和元数据，且不可恢复。')) return;

    setWorking(true);
    setError('');
    try {
      const result = await clearAllDocuments();
      setChunkData(null);
      setSelectedId('');
      onRefresh();
      onDataChanged?.();
      if (!result.success) {
        setError(result.error ?? '清空失败');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '清空失败');
    } finally {
      setWorking(false);
    }
  };

  return (
    <section className="panel panel-documents">
      <header className="panel-header">
        <h2>文档管理</h2>
        <div className="actions-row no-margin">
          <button onClick={onRefresh} disabled={loading || working}>{loading ? '刷新中...' : '刷新列表'}</button>
          <button className="danger-btn" onClick={removeAllDocs} disabled={loading || working || documents.length === 0}>
            清空全部文档
          </button>
        </div>
      </header>

      <div className="form-grid">
        <label>
          doc_type
          <input
            value={docType}
            onChange={(e) => onFilterChange({ docType: e.target.value, keyword, includeDeleted })}
            placeholder="例如 internal_regulation"
          />
        </label>
        <label>
          keyword
          <input
            value={keyword}
            onChange={(e) => onFilterChange({ docType, keyword: e.target.value, includeDeleted })}
            placeholder="文件名关键字"
          />
        </label>
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={includeDeleted}
            onChange={(e) => onFilterChange({ docType, keyword, includeDeleted: e.target.checked })}
          />
          包含已删除文档
        </label>
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={includeText}
            onChange={(e) => setIncludeText(e.target.checked)}
          />
          查看分块全文
        </label>
      </div>

      {error ? <p className="error-text">{error}</p> : null}

      <div className="documents-layout">
        <div className="documents-list">
          {documents.map((doc) => (
            <button
              key={doc.doc_id}
              className={`doc-row ${selectedId === doc.doc_id ? 'active' : ''}`}
              onClick={() => loadDetail(doc.doc_id)}
              disabled={working}
            >
              <strong>{doc.filename || doc.doc_id}</strong>
              <span>{doc.doc_type}</span>
              <span>{doc.chunk_count} chunks</span>
              <span className={`status-pill ${doc.status}`}>{doc.status}</span>
            </button>
          ))}
          {documents.length === 0 ? <p className="muted">没有匹配的文档</p> : null}
        </div>

        <div className="documents-detail">
          {selected ? (
            <>
              <div className="detail-head">
                <h3>{selected.filename}</h3>
                <button onClick={removeDoc} disabled={working}>删除文档</button>
              </div>
              <p className="muted">doc_id: {selected.doc_id}</p>
              <p className="muted">上传时间: {selected.upload_time}</p>
              <p className="muted">版本: {selected.version} | 文件大小: {selected.file_size} bytes</p>

              <div className="chunks-list">
                {(chunkData?.chunks ?? []).map((chunk) => (
                  <article key={chunk.chunk_id} className="chunk-item">
                    <div className="result-head">
                      <strong>{chunk.chunk_id}</strong>
                      <span>{chunk.char_count} chars</span>
                    </div>
                    <p>{includeText ? chunk.text : chunk.text_preview}</p>
                  </article>
                ))}
                {!working && selected && (chunkData?.chunks.length ?? 0) === 0 ? <p className="muted">该文档暂无分块数据</p> : null}
              </div>
            </>
          ) : (
            <p className="muted">左侧选择一个文档查看详情</p>
          )}
        </div>
      </div>
    </section>
  );
}
