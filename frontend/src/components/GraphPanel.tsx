import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  getGraphEdges,
  getGraphNodeDetail,
  getGraphNodes,
  getGraphOverview,
  getGraphSubgraph,
  rebuildGraphIndex
} from '../api/rag';
import type { GraphEdgeItem, GraphNodeDetailResponse, GraphNodeItem, GraphOverviewResponse } from '../types/rag';
import { GraphCanvas } from './GraphCanvas';
import { GraphNodeDrawer } from './GraphNodeDrawer';
import { GraphOverview } from './GraphOverview';
import { GraphPathExplorer } from './GraphPathExplorer';

interface GraphPanelProps {
  graphTypes?: string[];
  graphTypeLabels?: Record<string, string>;
  onGraphChanged?: () => void;
}

const PAGE_SIZE = 20;
const EVIDENCE_NODE_TYPES = new Set(['chunk', 'document']);

export function GraphPanel({ graphTypes = [], graphTypeLabels = {}, onGraphChanged }: GraphPanelProps) {
  const [includeEvidenceNodes, setIncludeEvidenceNodes] = useState(false);
  const [nodeKeyword, setNodeKeyword] = useState('');
  const [nodeType, setNodeType] = useState('');
  const [nodePage, setNodePage] = useState(1);
  const [nodes, setNodes] = useState<GraphNodeItem[]>([]);
  const [nodeTypeOptions, setNodeTypeOptions] = useState<Record<string, string>>({});
  const [nodesTotal, setNodesTotal] = useState(0);
  const [nodesLoading, setNodesLoading] = useState(false);

  const [edgeKeyword, setEdgeKeyword] = useState('');
  const [relation, setRelation] = useState('');
  const [edgePage, setEdgePage] = useState(1);
  const [edges, setEdges] = useState<GraphEdgeItem[]>([]);
  const [relationOptions, setRelationOptions] = useState<Record<string, string>>({});
  const [edgesTotal, setEdgesTotal] = useState(0);
  const [edgesLoading, setEdgesLoading] = useState(false);

  const [subgraphQuery, setSubgraphQuery] = useState('');
  const [subgraphHops, setSubgraphHops] = useState(2);
  const [subgraphMaxNodes, setSubgraphMaxNodes] = useState(120);
  const [subgraphNodes, setSubgraphNodes] = useState<GraphNodeItem[]>([]);
  const [subgraphEdges, setSubgraphEdges] = useState<GraphEdgeItem[]>([]);
  const [subgraphSeedNodes, setSubgraphSeedNodes] = useState<string[]>([]);
  const [subgraphLoading, setSubgraphLoading] = useState(false);

  const [overview, setOverview] = useState<GraphOverviewResponse | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const [detail, setDetail] = useState<GraphNodeDetailResponse | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState('');

  const [rebuilding, setRebuilding] = useState(false);
  const [error, setError] = useState('');

  const totalNodePages = Math.max(1, Math.ceil(nodesTotal / PAGE_SIZE));
  const totalEdgePages = Math.max(1, Math.ceil(edgesTotal / PAGE_SIZE));

  const discoveredNodeTypes = useMemo(() => {
    const initialTypes = includeEvidenceNodes
      ? graphTypes
      : graphTypes.filter((item) => !EVIDENCE_NODE_TYPES.has(item));
    const set = new Set<string>(initialTypes);
    for (const item of Object.keys(nodeTypeOptions)) {
      if (item) set.add(item);
    }
    for (const node of nodes) {
      if (node.type) set.add(node.type);
    }
    for (const node of subgraphNodes) {
      if (node.type) set.add(node.type);
    }
    return Array.from(set).sort();
  }, [graphTypes, nodeTypeOptions, nodes, subgraphNodes, includeEvidenceNodes]);

  const nodeTypeLabelMap = useMemo(() => {
    const map: Record<string, string> = { ...graphTypeLabels, ...nodeTypeOptions };
    for (const node of nodes) {
      if (node.type && node.type_label) {
        map[node.type] = node.type_label;
      }
    }
    for (const node of subgraphNodes) {
      if (node.type && node.type_label) {
        map[node.type] = node.type_label;
      }
    }
    return map;
  }, [graphTypeLabels, nodeTypeOptions, nodes, subgraphNodes]);

  const discoveredRelations = useMemo(() => {
    const set = new Set<string>(Object.keys(relationOptions));
    for (const edge of edges) {
      if (edge.relation) set.add(edge.relation);
    }
    for (const edge of subgraphEdges) {
      if (edge.relation) set.add(edge.relation);
    }
    return Array.from(set).sort();
  }, [relationOptions, edges, subgraphEdges]);

  const relationLabelMap = useMemo(() => {
    const map: Record<string, string> = { ...relationOptions };
    for (const edge of edges) {
      if (edge.relation && edge.relation_label) {
        map[edge.relation] = edge.relation_label;
      }
    }
    for (const edge of subgraphEdges) {
      if (edge.relation && edge.relation_label) {
        map[edge.relation] = edge.relation_label;
      }
    }
    return map;
  }, [relationOptions, edges, subgraphEdges]);

  const loadNodes = useCallback(async () => {
    setNodesLoading(true);
    setError('');
    try {
      const data = await getGraphNodes({
        page: nodePage,
        pageSize: PAGE_SIZE,
        nodeType,
        keyword: nodeKeyword,
        includeEvidenceNodes
      });
      setNodes(data.nodes);
      setNodeTypeOptions(
        Object.fromEntries((data.type_options ?? []).map((item) => [item.value, item.label]))
      );
      setNodesTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载图节点失败');
    } finally {
      setNodesLoading(false);
    }
  }, [nodeKeyword, nodePage, nodeType, includeEvidenceNodes]);

  const loadEdges = useCallback(async () => {
    setEdgesLoading(true);
    setError('');
    try {
      const data = await getGraphEdges({
        page: edgePage,
        pageSize: PAGE_SIZE,
        relation,
        keyword: edgeKeyword,
        includeEvidenceNodes
      });
      setEdges(data.edges);
      setRelationOptions(
        Object.fromEntries((data.relation_options ?? []).map((item) => [item.value, item.label]))
      );
      setEdgesTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载图边失败');
    } finally {
      setEdgesLoading(false);
    }
  }, [edgeKeyword, edgePage, relation, includeEvidenceNodes]);

  const loadOverview = useCallback(async () => {
    setOverviewLoading(true);
    try {
      const data = await getGraphOverview({ topN: 8 });
      setOverview(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载图谱总览失败');
    } finally {
      setOverviewLoading(false);
    }
  }, []);

  const openNodeDetail = useCallback(async (nodeId: string) => {
    if (!nodeId) return;
    setDetailOpen(true);
    setDetailLoading(true);
    setDetailError('');
    setDetail(null);
    setSelectedNodeId(nodeId);
    try {
      const data = await getGraphNodeDetail(nodeId, 120);
      setDetail(data);
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : '加载节点详情失败');
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadNodes();
  }, [loadNodes]);

  useEffect(() => {
    void loadEdges();
  }, [loadEdges]);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  useEffect(() => {
    if (includeEvidenceNodes) return;
    if (EVIDENCE_NODE_TYPES.has(nodeType)) {
      setNodeType('');
      setNodePage(1);
    }
  }, [includeEvidenceNodes, nodeType]);

  const handleRebuild = async () => {
    setRebuilding(true);
    setError('');
    try {
      await rebuildGraphIndex();
      await Promise.all([loadNodes(), loadEdges(), loadOverview()]);
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
        maxNodes: subgraphMaxNodes,
        includeEvidenceNodes
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
          <button
            onClick={() => {
              void loadNodes();
              void loadEdges();
              void loadOverview();
            }}
            disabled={nodesLoading || edgesLoading || rebuilding}
          >
            {nodesLoading || edgesLoading ? '刷新中...' : '刷新'}
          </button>
        </div>
      </header>

      <GraphOverview overview={overview} loading={overviewLoading} onRefresh={() => { void loadOverview(); }} />

      <div className="checkbox-row graph-scope-toggle">
        <input
          id="graph-scope-toggle"
          type="checkbox"
          checked={includeEvidenceNodes}
          onChange={(event) => {
            setIncludeEvidenceNodes(event.target.checked);
            setNodePage(1);
            setEdgePage(1);
          }}
        />
        <label htmlFor="graph-scope-toggle">
          显示证据层节点（document/chunk）
        </label>
      </div>

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
                  <option key={item} value={item}>{nodeTypeLabelMap[item] ?? item}</option>
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
                  <th>类型</th>
                  <th>名称</th>
                </tr>
              </thead>
              <tbody>
                {nodes.map((node) => (
                  <tr
                    key={node.id}
                    className={selectedNodeId === node.id ? 'row-active' : ''}
                    onClick={() => { void openNodeDetail(node.id); }}
                  >
                    <td>{node.id}</td>
                    <td>{node.type_label ?? nodeTypeLabelMap[node.type] ?? node.type}</td>
                    <td>{node.name_label ?? node.name}</td>
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
                  <option key={item} value={item}>{relationLabelMap[item] ?? item}</option>
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
                  <th>起点</th>
                  <th>关系</th>
                  <th>终点</th>
                </tr>
              </thead>
              <tbody>
                {edges.map((edge, idx) => (
                  <tr key={`${edge.source}-${edge.target}-${edge.relation}-${idx}`}>
                    <td>
                      <button type="button" className="link-btn" onClick={() => { void openNodeDetail(edge.source); }}>
                        {edge.source_name_label ?? edge.source_name}
                      </button>
                    </td>
                    <td>
                      {edge.relation_label ?? relationLabelMap[edge.relation] ?? edge.relation}
                      {Number((edge.attrs as { evidence_count?: number } | undefined)?.evidence_count || 0) > 1 ? (
                        <small className="muted"> ×{Number((edge.attrs as { evidence_count?: number }).evidence_count)}</small>
                      ) : null}
                    </td>
                    <td>
                      <button type="button" className="link-btn" onClick={() => { void openNodeDetail(edge.target); }}>
                        {edge.target_name_label ?? edge.target_name}
                      </button>
                    </td>
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
            跳数
            <input type="number" min={1} max={4} value={subgraphHops} onChange={(e) => setSubgraphHops(Number(e.target.value || 2))} />
          </label>
          <label>
            最大节点数
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

        <GraphCanvas
          nodes={subgraphNodes}
          edges={subgraphEdges}
          seedNodeIds={subgraphSeedNodes}
          selectedNodeId={selectedNodeId}
          onSelectNode={(nodeId) => { void openNodeDetail(nodeId); }}
        />

        <div className="graph-browser-grid">
          <div className="graph-table-wrap">
            <table className="graph-table">
              <thead>
                <tr>
                  <th>节点</th>
                  <th>类型</th>
                </tr>
              </thead>
              <tbody>
                {subgraphNodes.map((node) => (
                  <tr
                    key={`sub-node-${node.id}`}
                    className={selectedNodeId === node.id ? 'row-active' : ''}
                    onClick={() => { void openNodeDetail(node.id); }}
                  >
                    <td>{node.name_label ?? node.name}</td>
                    <td>{node.type_label ?? nodeTypeLabelMap[node.type] ?? node.type}</td>
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
                  <th>起点</th>
                  <th>关系</th>
                  <th>终点</th>
                </tr>
              </thead>
              <tbody>
                {subgraphEdges.map((edge, idx) => (
                  <tr key={`sub-edge-${edge.source}-${edge.target}-${edge.relation}-${idx}`}>
                    <td>
                      <button type="button" className="link-btn" onClick={() => { void openNodeDetail(edge.source); }}>
                        {edge.source_name_label ?? edge.source_name}
                      </button>
                    </td>
                    <td>
                      {edge.relation_label ?? relationLabelMap[edge.relation] ?? edge.relation}
                      {Number((edge.attrs as { evidence_count?: number } | undefined)?.evidence_count || 0) > 1 ? (
                        <small className="muted"> ×{Number((edge.attrs as { evidence_count?: number }).evidence_count)}</small>
                      ) : null}
                    </td>
                    <td>
                      <button type="button" className="link-btn" onClick={() => { void openNodeDetail(edge.target); }}>
                        {edge.target_name_label ?? edge.target_name}
                      </button>
                    </td>
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

      <GraphPathExplorer
        includeEvidenceNodes={includeEvidenceNodes}
        onSelectNode={(nodeId) => {
          void openNodeDetail(nodeId);
        }}
      />

      <GraphNodeDrawer
        open={detailOpen}
        detail={detail}
        loading={detailLoading}
        error={detailError}
        onClose={() => {
          setDetailOpen(false);
          setDetailError('');
          setDetail(null);
          setSelectedNodeId('');
        }}
      />
    </section>
  );
}
