import { useEffect, useState } from 'react';
import { getGraphPath } from '../api/rag';
import type { GraphPathResponse } from '../types/rag';

interface GraphPathExplorerProps {
  onSelectNode?: (nodeId: string) => void;
  includeEvidenceNodes?: boolean;
}

export function GraphPathExplorer({ onSelectNode, includeEvidenceNodes = false }: GraphPathExplorerProps) {
  const [sourceQuery, setSourceQuery] = useState('');
  const [targetQuery, setTargetQuery] = useState('');
  const [maxHops, setMaxHops] = useState(4);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<GraphPathResponse | null>(null);

  useEffect(() => {
    setResult(null);
    setError('');
  }, [includeEvidenceNodes]);

  const run = async () => {
    const from = sourceQuery.trim();
    const to = targetQuery.trim();
    if (!from || !to) {
      setError('请输入起点和终点关键词');
      return;
    }

    setLoading(true);
    setError('');
    try {
      const data = await getGraphPath({
        sourceQuery: from,
        targetQuery: to,
        maxHops,
        includeEvidenceNodes
      });
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '路径查询失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <article className="graph-section graph-path-explorer">
      <header className="graph-section-header">
        <h3>路径探索</h3>
        <small className="muted">
          查找两类实体之间的最短关联路径（{includeEvidenceNodes ? '含证据层' : '语义层'}）
        </small>
      </header>

      <div className="form-grid">
        <label>
          起点关键词
          <input
            value={sourceQuery}
            onChange={(event) => setSourceQuery(event.target.value)}
            placeholder="例如：采购管理"
          />
        </label>
        <label>
          终点关键词
          <input
            value={targetQuery}
            onChange={(event) => setTargetQuery(event.target.value)}
            placeholder="例如：整改措施"
          />
        </label>
        <label>
          最大跳数
          <input
            type="number"
            min={1}
            max={8}
            value={maxHops}
            onChange={(event) => setMaxHops(Number(event.target.value || 4))}
          />
        </label>
      </div>

      <div className="actions-row">
        <button onClick={run} disabled={loading}>{loading ? '查询中...' : '查询路径'}</button>
      </div>

      {error ? <p className="error-text">{error}</p> : null}

      {result ? (
        <div className="graph-path-result">
          <div className="status-inline">
            <span>
              <strong>起点</strong>: {result.source_node ? (result.source_node.name_label ?? result.source_node.name) : '未命中'}
            </span>
            <span>
              <strong>终点</strong>: {result.target_node ? (result.target_node.name_label ?? result.target_node.name) : '未命中'}
            </span>
            <span>
              <strong>跳数</strong>: {result.hops}
            </span>
          </div>

          {result.path_found ? (
            <>
              <p className="graph-path-text">{result.path_text}</p>

              <div className="graph-table-wrap">
                <table className="graph-table">
                  <thead>
                    <tr>
                      <th>起点</th>
                      <th>关系</th>
                      <th>终点</th>
                      <th>方向</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.path_edges.map((edge, index) => (
                      <tr key={`path-${edge.source}-${edge.target}-${edge.relation}-${index}`}>
                        <td>
                          <button type="button" className="link-btn" onClick={() => onSelectNode?.(edge.source)}>
                            {edge.source_name_label ?? edge.source_name}
                          </button>
                        </td>
                        <td>{edge.relation_label ?? edge.relation}</td>
                        <td>
                          <button type="button" className="link-btn" onClick={() => onSelectNode?.(edge.target)}>
                            {edge.target_name_label ?? edge.target_name}
                          </button>
                        </td>
                        <td>{edge.direction === 'reverse' ? '逆向' : '正向'}</td>
                      </tr>
                    ))}
                    {result.path_edges.length === 0 ? (
                      <tr>
                        <td colSpan={4} className="muted">起点与终点相同</td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <p className="muted">在最大跳数内未找到可达路径</p>
          )}

          <div className="graph-overview-grid">
            <section className="graph-overview-card">
              <h4>起点候选</h4>
              <div className="chip-row">
                {(result.source_candidates || []).map((item) => (
                  <button key={`source-candidate-${item.id}`} type="button" className="chip link-chip" onClick={() => onSelectNode?.(item.id)}>
                    <span>{item.name_label ?? item.name}</span>
                    <strong>{item.type_label ?? item.type}</strong>
                  </button>
                ))}
                {(result.source_candidates || []).length === 0 ? <span className="muted">无候选</span> : null}
              </div>
            </section>

            <section className="graph-overview-card">
              <h4>终点候选</h4>
              <div className="chip-row">
                {(result.target_candidates || []).map((item) => (
                  <button key={`target-candidate-${item.id}`} type="button" className="chip link-chip" onClick={() => onSelectNode?.(item.id)}>
                    <span>{item.name_label ?? item.name}</span>
                    <strong>{item.type_label ?? item.type}</strong>
                  </button>
                ))}
                {(result.target_candidates || []).length === 0 ? <span className="muted">无候选</span> : null}
              </div>
            </section>
          </div>
        </div>
      ) : null}
    </article>
  );
}
