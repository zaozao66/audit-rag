import type { GraphNodeDetailResponse } from '../types/rag';

interface GraphNodeDrawerProps {
  open: boolean;
  detail: GraphNodeDetailResponse | null;
  loading: boolean;
  error: string;
  onClose: () => void;
}

export function GraphNodeDrawer({ open, detail, loading, error, onClose }: GraphNodeDrawerProps) {
  if (!open) return null;

  return (
    <div className="graph-drawer-overlay" onClick={onClose}>
      <aside className="graph-drawer" onClick={(event) => event.stopPropagation()}>
        <header className="graph-drawer-header">
          <div>
            <h3>节点详情</h3>
            <small className="muted">{detail?.node?.type_label ?? '-'}</small>
          </div>
          <button type="button" className="secondary-btn" onClick={onClose}>关闭</button>
        </header>

        {loading ? <p className="muted">加载中...</p> : null}
        {error ? <p className="error-text">{error}</p> : null}

        {!loading && !error && detail ? (
          <div className="graph-drawer-content">
            <section className="graph-drawer-block">
              <h4>{detail.node.name_label ?? detail.node.name}</h4>
              <p className="muted">ID: {detail.node.id}</p>
            </section>

            <section className="graph-drawer-block">
              <h4>关联统计</h4>
              <div className="chip-row">
                <div className="chip"><span>出边</span><strong>{detail.outgoing_edges.length}</strong></div>
                <div className="chip"><span>入边</span><strong>{detail.incoming_edges.length}</strong></div>
                <div className="chip"><span>邻居节点</span><strong>{detail.neighbors.length}</strong></div>
                <div className="chip"><span>证据源</span><strong>{detail.sources.length}</strong></div>
              </div>
            </section>

            <section className="graph-drawer-block">
              <h4>关系明细</h4>
              <div className="graph-table-wrap">
                <table className="graph-table">
                  <thead>
                    <tr>
                      <th>方向</th>
                      <th>关系</th>
                      <th>对端节点</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.outgoing_edges.map((edge, idx) => (
                      <tr key={`out-${idx}-${edge.target}-${edge.relation}`}>
                        <td>出</td>
                        <td>{edge.relation_label ?? edge.relation}</td>
                        <td>{edge.target_name_label ?? edge.target_name}</td>
                      </tr>
                    ))}
                    {detail.incoming_edges.map((edge, idx) => (
                      <tr key={`in-${idx}-${edge.source}-${edge.relation}`}>
                        <td>入</td>
                        <td>{edge.relation_label ?? edge.relation}</td>
                        <td>{edge.source_name_label ?? edge.source_name}</td>
                      </tr>
                    ))}
                    {detail.outgoing_edges.length === 0 && detail.incoming_edges.length === 0 ? (
                      <tr>
                        <td colSpan={3} className="muted">暂无关系</td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="graph-drawer-block">
              <h4>来源片段</h4>
              <div className="citation-list">
                {detail.source_chunks.map((chunk) => (
                  <article key={`chunk-${chunk.chunk_id}`} className="citation-card">
                    <header>
                      <span>{chunk.filename || chunk.title || chunk.doc_id}</span>
                      <small>{chunk.doc_type_label ?? chunk.doc_type}</small>
                    </header>
                    <p>{chunk.text_preview || '无内容摘要'}</p>
                    <footer>
                      <small>chunk: {chunk.chunk_id}</small>
                      <small>pages: {(chunk.page_nos || []).join(',') || '-'}</small>
                    </footer>
                  </article>
                ))}
                {detail.source_chunks.length === 0 ? <p className="muted">暂无来源片段</p> : null}
              </div>
            </section>
          </div>
        ) : null}
      </aside>
    </div>
  );
}
