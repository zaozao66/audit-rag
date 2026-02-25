import type { GraphOverviewResponse } from '../types/rag';

interface GraphOverviewProps {
  overview: GraphOverviewResponse | null;
  loading: boolean;
  onRefresh: () => void;
}

export function GraphOverview({ overview, loading, onRefresh }: GraphOverviewProps) {
  const density = overview && overview.nodes > 0 ? (overview.edges / overview.nodes).toFixed(2) : '0.00';

  return (
    <article className="graph-section graph-overview">
      <header className="graph-section-header">
        <h3>图谱总览</h3>
        <button type="button" className="secondary-btn" onClick={onRefresh} disabled={loading}>
          {loading ? '加载中...' : '刷新总览'}
        </button>
      </header>

      <div className="metrics-grid">
        <div className="metric-card">
          <span>节点总数</span>
          <strong>{overview?.nodes ?? 0}</strong>
        </div>
        <div className="metric-card">
          <span>边总数</span>
          <strong>{overview?.edges ?? 0}</strong>
        </div>
        <div className="metric-card">
          <span>边/节点密度</span>
          <strong>{density}</strong>
        </div>
      </div>

      <div className="graph-overview-grid">
        <section className="graph-overview-card">
          <h4>实体类型分布</h4>
          <div className="chip-row">
            {(overview?.node_type_distribution ?? []).slice(0, 8).map((item) => (
              <div key={`type-${item.type}`} className="chip">
                <span>{item.label}</span>
                <strong>{item.count}</strong>
              </div>
            ))}
          </div>
        </section>

        <section className="graph-overview-card">
          <h4>关系 Top</h4>
          <div className="chip-row">
            {(overview?.relation_distribution ?? []).slice(0, 8).map((item) => (
              <div key={`rel-${item.relation}`} className="chip">
                <span>{item.label}</span>
                <strong>{item.count}</strong>
              </div>
            ))}
          </div>
        </section>

        <section className="graph-overview-card">
          <h4>整改状态分布</h4>
          <div className="chip-row">
            {(overview?.rectification_status_distribution ?? []).slice(0, 8).map((item) => (
              <div key={`status-${item.status}`} className="chip">
                <span>{item.label}</span>
                <strong>{item.count}</strong>
              </div>
            ))}
          </div>
        </section>

        <section className="graph-overview-card">
          <h4>部门问题 Top</h4>
          <div className="chip-row">
            {(overview?.department_issue_top ?? []).slice(0, 8).map((item) => (
              <div key={`dept-${item.department}`} className="chip">
                <span>{item.department}</span>
                <strong>{item.issue_count}</strong>
              </div>
            ))}
          </div>
        </section>
      </div>
    </article>
  );
}
