import { useState } from 'react';
import { rebuildGraphIndex } from '../api/rag';
import type { DocumentStats, InfoResponse } from '../types/rag';

interface SystemPanelProps {
  info: InfoResponse | null;
  stats: DocumentStats | null;
  loading: boolean;
  onRefresh: () => void;
}

export function SystemPanel({ info, stats, loading, onRefresh }: SystemPanelProps) {
  const [rebuildingGraph, setRebuildingGraph] = useState(false);
  const [graphActionMsg, setGraphActionMsg] = useState('');

  const handleRebuildGraph = async () => {
    setRebuildingGraph(true);
    setGraphActionMsg('');
    try {
      const result = await rebuildGraphIndex();
      setGraphActionMsg(result.message || '图索引重建完成');
      onRefresh();
    } catch (err) {
      setGraphActionMsg(err instanceof Error ? err.message : '图索引重建失败');
    } finally {
      setRebuildingGraph(false);
    }
  };

  return (
    <section className="panel panel-metric">
      <header className="panel-header">
        <h2>系统状态</h2>
        <div className="actions-row no-margin">
          <button className="secondary-btn" onClick={handleRebuildGraph} disabled={loading || rebuildingGraph}>
            {rebuildingGraph ? '重建中...' : '重建图索引'}
          </button>
          <button onClick={onRefresh} disabled={loading || rebuildingGraph}>
            {loading ? '刷新中...' : '刷新'}
          </button>
        </div>
      </header>

      <div className="metrics-grid">
        <Metric label="服务状态" value={info?.status ?? '-'} />
        <Metric label="向量库" value={info?.vector_store_status ?? '-'} />
        <Metric label="向量数量" value={String(info?.vector_count ?? 0)} />
        <Metric label="Embedding" value={info?.embedding_model ?? '-'} />
        <Metric label="图文件" value={info?.graph?.graph_file_exists ? '已生成' : '未生成'} />
        <Metric label="图节点数" value={String(info?.graph?.in_memory?.nodes ?? 0)} />
        <Metric label="图边数" value={String(info?.graph?.in_memory?.edges ?? 0)} />
        <Metric label="活跃文档" value={String(stats?.active_documents ?? 0)} />
        <Metric label="总分块" value={String(stats?.total_chunks ?? 0)} />
      </div>

      <div className="type-stats">
        <h3>图谱节点分布</h3>
        {info?.graph?.in_memory?.by_type && Object.keys(info.graph.in_memory.by_type).length > 0 ? (
          <div className="chip-row">
            {Object.entries(info.graph.in_memory.by_type).map(([type, value]) => (
              <div key={type} className="chip">
                <span>{type}</span>
                <strong>{value}</strong>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted">暂无图谱节点统计</p>
        )}
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

      {graphActionMsg ? <p className="muted">{graphActionMsg}</p> : null}
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
