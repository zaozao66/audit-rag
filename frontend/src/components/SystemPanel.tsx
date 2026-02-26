import { useState } from 'react';
import type { DocumentStats, InfoResponse } from '../types/rag';

interface SystemPanelProps {
  info: InfoResponse | null;
  stats: DocumentStats | null;
  loading: boolean;
  onRefresh: () => void;
}

export function SystemPanel({ info, stats, loading, onRefresh }: SystemPanelProps) {
  const [statusMsg, setStatusMsg] = useState('');

  const refresh = () => {
    setStatusMsg('已刷新');
    onRefresh();
  };

  return (
    <section className="panel panel-metric">
      <header className="panel-header">
        <h2>系统状态</h2>
        <div className="actions-row no-margin">
          <button onClick={refresh} disabled={loading}>
            {loading ? '刷新中...' : '刷新'}
          </button>
        </div>
      </header>

      <div className="metrics-grid">
        <Metric label="服务状态" value={info?.status ?? '-'} />
        <Metric label="向量库" value={info?.vector_store_status ?? '-'} />
        <Metric label="向量数量" value={String(info?.vector_count ?? 0)} />
        <Metric label="Embedding" value={info?.embedding_model ?? '-'} />
        <Metric label="分块策略" value={info?.chunker_type ?? '-'} />
        <Metric label="活跃文档" value={String(stats?.active_documents ?? 0)} />
        <Metric label="总分块" value={String(stats?.total_chunks ?? 0)} />
      </div>

      <div className="type-stats">
        <h3>文档类型分布</h3>
        {stats && Object.keys(stats.by_type).length > 0 ? (
          <div className="chip-row">
            {Object.entries(stats.by_type).map(([type, value]) => (
              <div key={type} className="chip">
                <span>{type}</span>
                <strong>{value.count} docs / {value.chunks} chunks</strong>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted">暂无文档类型统计</p>
        )}
      </div>

      {statusMsg ? <p className="muted">{statusMsg}</p> : null}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
