import { useState } from 'react';
import { uploadFiles } from '../api/rag';
import type { UploadResponse } from '../types/rag';

interface UploadPanelProps {
  onUploaded: () => void;
}

export function UploadPanel({ onUploaded }: UploadPanelProps) {
  const [files, setFiles] = useState<File[]>([]);
  const [chunkerType, setChunkerType] = useState('smart');
  const [docType, setDocType] = useState('internal_regulation');
  const [title, setTitle] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<UploadResponse | null>(null);
  const [error, setError] = useState('');

  const handleUpload = async () => {
    if (files.length === 0) {
      setError('请先选择至少一个文件');
      return;
    }

    setLoading(true);
    setError('');
    try {
      const data = await uploadFiles({ files, chunkerType, docType, title });
      setResult(data);
      onUploaded();
    } catch (err) {
      setError(err instanceof Error ? err.message : '上传失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="panel">
      <header className="panel-header">
        <h2>文件上传入库</h2>
      </header>

      <div className="form-grid">
        <label>
          上传文件
          <input
            type="file"
            multiple
            onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
            accept=".pdf,.doc,.docx,.txt"
          />
        </label>

        <label>
          分块器
          <select value={chunkerType} onChange={(e) => setChunkerType(e.target.value)}>
            <option value="smart">smart</option>
            <option value="regulation">regulation</option>
            <option value="audit_report">audit_report</option>
            <option value="audit_issue">audit_issue</option>
            <option value="default">default</option>
          </select>
        </label>

        <label>
          文档类型
          <select value={docType} onChange={(e) => setDocType(e.target.value)}>
            <option value="internal_regulation">internal_regulation</option>
            <option value="external_regulation">external_regulation</option>
            <option value="internal_report">internal_report</option>
            <option value="external_report">external_report</option>
            <option value="audit_issue">audit_issue</option>
          </select>
        </label>

        <label>
          标题（可选）
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="如：2025年度内审报告" />
        </label>
      </div>

      <div className="actions-row">
        <button onClick={handleUpload} disabled={loading}>
          {loading ? '上传处理中...' : '开始上传'}
        </button>
        <span className="muted">已选 {files.length} 个文件</span>
      </div>

      {error ? <p className="error-text">{error}</p> : null}
      {result ? (
        <div className="result-box">
          <p>{result.message}</p>
          <p>
            新增 {result.processed_count}，跳过 {result.skipped_count ?? 0}，更新 {result.updated_count ?? 0}，总分块 {result.total_chunks ?? 0}
          </p>
        </div>
      ) : null}
    </section>
  );
}
