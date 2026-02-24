import { useCallback, useEffect, useMemo, useState } from 'react';
import { getGraphEdges, getGraphNodes, getGraphSubgraph, rebuildGraphIndex } from '../api/rag';
import type { GraphEdgeItem, GraphNodeItem } from '../types/rag';

interface GraphPanelProps {
  graphTypes?: string[];
  onGraphChanged?: () => void;
}

const PAGE_SIZE = 20;

export function GraphPanel({ graphTypes = [], onGraphChanged }: GraphPanelProps) {
  const [nodeKeyword, setNodeKeyword] = useState('');
  const [nodeType, setNodeType] = useState('');
  const [nodePage, setNodePage] = useState(1);
  const [nodes, setNodes] = useState<GraphNodeItem[]>([]);
  const [nodesTotal, setNodesTotal] = useState(0);
  const [nodesLoading, setNodesLoading] = useState(false);

  const [edgeKeyword, setEdgeKeyword] = useState('');
  const [relation, setRelation] = useState('');
  const [edgePage, setEdgePage] = useState(1);
  const [edges, setEdges] = useState<GraphEdgeItem[]>([]);
  const [edgesTotal, setEdgesTotal] = useState(0);
  const [edgesLoading, setEdgesLoading] = useState(false);

  const [subgraphQuery, setSubgraphQuery] = useState('');
  const [subgraphHops, setSubgraphHops] = useState(2);
  const [subgraphMaxNodes, setSubgraphMaxNodes] = useState(120);
  const [subgraphNodes, setSubgraphNodes] = useState<GraphNodeItem[]>([]);
  const [subgraphEdges, setSubgraphEdges] = useState<GraphEdgeItem[]>([]);
  const [subgraphSeedNodes, setSubgraphSeedNodes] = useState<string[]>([]);
  const [subgraphLoading, setSubgraphLoading] = useState(false);

  const [rebuilding, setRebuilding] = useState(false);
  const [error, setError] = useState('');

  const totalNodePages = Math.max(1, Math.ceil(nodesTotal / PAGE_SIZE));
  const totalEdgePages = Math.max(1, Math.ceil(edgesTotal / PAGE_SIZE));

  const discoveredNodeTypes = useMemo(() => {
    const set = new Set<string>(graphTypes);
    for (const node of nodes) {
      if (node.type) set.add(node.type);
    }
    for (const node of subgraphNodes) {
      if (node.type) set.add(node.type);
    }
    return Array.from(set).sort();
  }, [graphTypes, nodes, subgraphNodes]);

  const discoveredRelations = useMemo(() => {
    const set = new Set<string>();
    for (const edge of edges) {
      if (edge.relation) set.add(edge.relation);
    }
    for (const edge of subgraphEdges) {
      if (edge.relation) set.add(edge.relation);
    }
    return Array.from(set).sort();
  }, [edges, subgraphEdges]);

  const loadNodes = useCallback(async () => {
    setNodesLoading(true);
    setError('');
    try {
      const data = await getGraphNodes({
        page: nodePage,
        pageSize: PAGE_SIZE,
        nodeType,
        keyword: nodeKeyword
      });
      setNodes(data.nodes);
      setNodesTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载图节点失败');
    } finally {
      setNodesLoading(false);
    }
  }, [nodeKeyword, nodePage, nodeType]);

  const loadEdges = useCallback(async () => {
    setEdgesLoading(true);
    setError('');
    try {
      const data = await getGraphEdges({
        page: edgePage,
        pageSize: PAGE_SIZE,
        relation,
        keyword: edgeKeyword
      });
      setEdges(data.edges);
      setEdgesTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载图边失败');
    } finally {
      setEdgesLoading(false);
    }
  }, [edgeKeyword, edgePage, relation]);

  useEffect(() => {
    void loadNodes();
  }, [loadNodes]);

  useEffect(() => {
    void loadEdges();
  }, [loadEdges]);

  const handleRebuild = async () => {
    setRebuilding(true);
    setError('');
    try {
      await rebuildGraphIndex();
      await Promise.all([loadNodes(), loadEdges()]);
      onGraphChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : '重建图索引失败');
    } finally {
      setRebuilding(false);
    }
  };

  const handleLoadSubgraph = async () => {
    if (!subgraphQuery.trim()) {
      setError('请输入子图查询关键词');
      return;
    }

    setSubgraphLoading(true);
    setError('');
    try {
      const data = await getGraphSubgraph({
        query: subgraphQuery.trim(),
        hops: subgraphHops,
        maxNodes: subgraphMaxNodes
      });
      setSubgraphNodes(data.nodes);
      setSubgraphEdges(data.edges);
      setSubgraphSeedNodes(data.seed_nodes || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载子图失败');
    } finally {
      setSubgraphLoading(false);
    }
  };

  return (
    <section className="panel panel-graph">
      <header className="panel-header">
        <h2>图谱浏览</h2>
        <div className="actions-row no-margin">
          <button className="secondary-btn" onClick={handleRebuild} disabled={rebuilding || nodesLoading || edgesLoading}>
            {rebuilding ? '重建中...' : '重建图索引'}
          </button>
          <button onClick={() => { void loadNodes(); void loadEdges(); }} disabled={nodesLoading || edgesLoading || rebuilding}>
            {nodesLoading || edgesLoading ? '刷新中...' : '刷新'}
          </button>
        </div>
      </header>

      {error ? <p className="error-text">{error}</p> : null}

      <div className="graph-browser-grid">
        <article className="graph-section">
          <header className="graph-section-header">
            <h3>节点列表</h3>
            <small className="muted">总计 {nodesTotal}</small>
          </header>

          <div className="form-grid">
            <label>
              类型
              <select value={nodeType} onChange={(e) => { setNodeType(e.target.value); setNodePage(1); }}>
                <option value="">全部</option>
                {discoveredNodeTypes.map((item) => (
                  <option key={item} value={item}>{item}</option>
                ))}
              </select>
            </label>
            <label>
              关键词
              <input
                value={nodeKeyword}
                onChange={(e) => { setNodeKeyword(e.target.value); setNodePage(1); }}
                placeholder="节点名/属性"
              />
            </label>
          </div>

          <div className="graph-table-wrap">
            <table className="graph-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Type</th>
                  <th>Name</th>
                </tr>
              </thead>
              <tbody>
                {nodes.map((node) => (
                  <tr key={node.id}>
                    <td>{node.id}</td>
                    <td>{node.type}</td>
                    <td>{node.name}</td>
                  </tr>
                ))}
                {!nodesLoading && nodes.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="muted">无匹配节点</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>

          <div className="pager-row">
            <button className="secondary-btn" onClick={() => setNodePage((p) => Math.max(1, p - 1))} disabled={nodePage <= 1 || nodesLoading}>上一页</button>
            <span className="muted">{nodePage} / {totalNodePages}</span>
            <button className="secondary-btn" onClick={() => setNodePage((p) => Math.min(totalNodePages, p + 1))} disabled={nodePage >= totalNodePages || nodesLoading}>下一页</button>
          </div>
        </article>

        <article className="graph-section">
          <header className="graph-section-header">
            <h3>边列表</h3>
            <small className="muted">总计 {edgesTotal}</small>
          </header>

          <div className="form-grid">
            <label>
              关系
              <select value={relation} onChange={(e) => { setRelation(e.target.value); setEdgePage(1); }}>
                <option value="">全部</option>
                {discoveredRelations.map((item) => (
                  <option key={item} value={item}>{item}</option>
                ))}
              </select>
            </label>
            <label>
              关键词
              <input
                value={edgeKeyword}
                onChange={(e) => { setEdgeKeyword(e.target.value); setEdgePage(1); }}
                placeholder="节点或关系"
              />
            </label>
          </div>

          <div className="graph-table-wrap">
            <table className="graph-table">
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Relation</th>
                  <th>Target</th>
                </tr>
              </thead>
              <tbody>
                {edges.map((edge, idx) => (
                  <tr key={`${edge.source}-${edge.target}-${edge.relation}-${idx}`}>
                    <td>{edge.source_name}</td>
                    <td>{edge.relation}</td>
                    <td>{edge.target_name}</td>
                  </tr>
                ))}
                {!edgesLoading && edges.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="muted">无匹配边</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>

          <div className="pager-row">
            <button className="secondary-btn" onClick={() => setEdgePage((p) => Math.max(1, p - 1))} disabled={edgePage <= 1 || edgesLoading}>上一页</button>
            <span className="muted">{edgePage} / {totalEdgePages}</span>
            <button className="secondary-btn" onClick={() => setEdgePage((p) => Math.min(totalEdgePages, p + 1))} disabled={edgePage >= totalEdgePages || edgesLoading}>下一页</button>
          </div>
        </article>
      </div>

      <article className="graph-section graph-subgraph">
        <header className="graph-section-header">
          <h3>局部子图探索</h3>
          <small className="muted">从关键词扩展关联关系</small>
        </header>

        <div className="form-grid">
          <label className="query-input">
            关键词
            <input value={subgraphQuery} onChange={(e) => setSubgraphQuery(e.target.value)} placeholder="例如：整改 / 采购 / 审计法" />
          </label>
          <label>
            hops
            <input type="number" min={1} max={4} value={subgraphHops} onChange={(e) => setSubgraphHops(Number(e.target.value || 2))} />
          </label>
          <label>
            max_nodes
            <input type="number" min={20} max={300} value={subgraphMaxNodes} onChange={(e) => setSubgraphMaxNodes(Number(e.target.value || 120))} />
          </label>
        </div>

        <div className="actions-row">
          <button onClick={handleLoadSubgraph} disabled={subgraphLoading}>{subgraphLoading ? '加载中...' : '加载子图'}</button>
        </div>

        <div className="status-inline">
          <span><strong>种子节点</strong>: {subgraphSeedNodes.length}</span>
          <span><strong>子图节点</strong>: {subgraphNodes.length}</span>
          <span><strong>子图边</strong>: {subgraphEdges.length}</span>
        </div>

        <div className="graph-browser-grid">
          <div className="graph-table-wrap">
            <table className="graph-table">
              <thead>
                <tr>
                  <th>Node</th>
                  <th>Type</th>
                </tr>
              </thead>
              <tbody>
                {subgraphNodes.map((node) => (
                  <tr key={`sub-node-${node.id}`}>
                    <td>{node.name}</td>
                    <td>{node.type}</td>
                  </tr>
                ))}
                {!subgraphLoading && subgraphNodes.length === 0 ? (
                  <tr>
                    <td colSpan={2} className="muted">暂无子图节点</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>

          <div className="graph-table-wrap">
            <table className="graph-table">
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Relation</th>
                  <th>Target</th>
                </tr>
              </thead>
              <tbody>
                {subgraphEdges.map((edge, idx) => (
                  <tr key={`sub-edge-${edge.source}-${edge.target}-${edge.relation}-${idx}`}>
                    <td>{edge.source_name}</td>
                    <td>{edge.relation}</td>
                    <td>{edge.target_name}</td>
                  </tr>
                ))}
                {!subgraphLoading && subgraphEdges.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="muted">暂无子图边</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </div>
      </article>
    </section>
  );
}
