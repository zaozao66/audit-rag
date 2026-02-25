import { useMemo, useRef, useState } from 'react';
import type { MouseEvent as ReactMouseEvent, WheelEvent as ReactWheelEvent } from 'react';
import type { GraphEdgeItem, GraphNodeItem } from '../types/rag';

interface GraphCanvasProps {
  nodes: GraphNodeItem[];
  edges: GraphEdgeItem[];
  seedNodeIds: string[];
  selectedNodeId?: string;
  onSelectNode?: (nodeId: string) => void;
}

const WIDTH = 980;
const HEIGHT = 460;

export function GraphCanvas({ nodes, edges, seedNodeIds, selectedNodeId, onSelectNode }: GraphCanvasProps) {
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const dragRef = useRef<{ x: number; y: number; active: boolean }>({ x: 0, y: 0, active: false });

  const positions = useMemo(() => {
    const seedSet = new Set(seedNodeIds);
    const seeds = nodes.filter((item) => seedSet.has(item.id));
    const others = nodes.filter((item) => !seedSet.has(item.id));

    const map: Record<string, { x: number; y: number }> = {};
    const cx = WIDTH / 2;
    const cy = HEIGHT / 2;

    const place = (items: GraphNodeItem[], radius: number, startAngle: number) => {
      if (items.length === 0) return;
      for (let i = 0; i < items.length; i += 1) {
        const angle = startAngle + (Math.PI * 2 * i) / items.length;
        map[items[i].id] = {
          x: cx + radius * Math.cos(angle),
          y: cy + radius * Math.sin(angle)
        };
      }
    };

    place(seeds, Math.min(WIDTH, HEIGHT) * 0.2, -Math.PI / 2);
    place(others, Math.min(WIDTH, HEIGHT) * 0.36, -Math.PI / 2);
    return map;
  }, [nodes, seedNodeIds]);

  const renderedEdges = useMemo(() => {
    if (edges.length <= 280) return edges;
    return edges.slice(0, 280);
  }, [edges]);

  const handleWheel = (event: ReactWheelEvent<SVGSVGElement>) => {
    event.preventDefault();
    setScale((prev) => {
      const next = prev + (event.deltaY < 0 ? 0.08 : -0.08);
      return Math.max(0.45, Math.min(2.4, next));
    });
  };

  const handleMouseDown = (event: ReactMouseEvent<SVGSVGElement>) => {
    dragRef.current = {
      x: event.clientX - offset.x,
      y: event.clientY - offset.y,
      active: true
    };
  };

  const handleMouseMove = (event: ReactMouseEvent<SVGSVGElement>) => {
    if (!dragRef.current.active) return;
    setOffset({
      x: event.clientX - dragRef.current.x,
      y: event.clientY - dragRef.current.y
    });
  };

  const handleMouseUp = () => {
    dragRef.current.active = false;
  };

  return (
    <section className="graph-canvas-wrap">
      <header className="graph-section-header">
        <h4>子图可视化</h4>
        <div className="actions-row no-margin">
          <button type="button" className="secondary-btn" onClick={() => setScale((prev) => Math.max(0.45, prev - 0.1))}>缩小</button>
          <button type="button" className="secondary-btn" onClick={() => setScale((prev) => Math.min(2.4, prev + 0.1))}>放大</button>
          <button type="button" className="secondary-btn" onClick={() => { setScale(1); setOffset({ x: 0, y: 0 }); }}>重置</button>
        </div>
      </header>

      <div className="graph-canvas-hint">
        <small className="muted">拖拽平移，滚轮缩放，点击节点查看详情</small>
      </div>

      <svg
        className="graph-canvas"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        <g transform={`translate(${offset.x} ${offset.y}) scale(${scale})`}>
          {renderedEdges.map((edge, index) => {
            const from = positions[edge.source];
            const to = positions[edge.target];
            if (!from || !to) return null;
            return (
              <line
                key={`edge-${edge.source}-${edge.target}-${edge.relation}-${index}`}
                x1={from.x}
                y1={from.y}
                x2={to.x}
                y2={to.y}
                className="graph-canvas-edge"
              />
            );
          })}

          {nodes.map((node) => {
            const pos = positions[node.id];
            if (!pos) return null;
            const selected = node.id === selectedNodeId;
            return (
              <g
                key={node.id}
                className={`graph-canvas-node ${selected ? 'selected' : ''}`}
                transform={`translate(${pos.x}, ${pos.y})`}
                onClick={() => onSelectNode?.(node.id)}
              >
                <circle r={selected ? 20 : 16} fill={nodeColor(node.type)} />
                <text y={30} textAnchor="middle">{(node.name_label ?? node.name).slice(0, 10)}</text>
              </g>
            );
          })}
        </g>
      </svg>
    </section>
  );
}

function nodeColor(type: string): string {
  switch (type) {
    case 'issue':
      return '#c94c4c';
    case 'department':
      return '#4f6d7a';
    case 'rectification_action':
      return '#0c7c59';
    case 'rectification_status':
      return '#f59e0b';
    case 'clause':
      return '#6b7280';
    case 'risk_type':
      return '#8b5cf6';
    case 'chunk':
      return '#64748b';
    case 'document':
      return '#334155';
    default:
      return '#7d6a58';
  }
}
