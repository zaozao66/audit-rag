import { useMemo, useRef, useState } from 'react';
import type { MouseEvent as ReactMouseEvent } from 'react';
import { streamAskWithLlm } from '../api/rag';
import type { CitationItem, StreamProgressEvent } from '../types/rag';
import { renderMarkdownToHtml } from '../utils/markdown';

const STAGE_LABEL: Record<StreamProgressEvent['stage'], string> = {
  intent: '意图识别',
  retrieval: '检索召回',
  generation: '回答生成'
};

interface CitationListProps {
  items: CitationItem[];
  keyPrefix: string;
  showScores?: boolean;
  useAnchorId?: boolean;
  anchorPrefix?: string;
}

function CitationList({
  items,
  keyPrefix,
  showScores = false,
  useAnchorId = false,
  anchorPrefix = ''
}: CitationListProps) {
  return (
    <div className="citation-list">
      {items.map((item) => (
        <article
          key={`${keyPrefix}-${item.source_id}`}
          id={useAnchorId ? `${anchorPrefix}cite-${item.source_id}` : undefined}
          className="citation-card"
        >
          <header>
            <span>[{item.source_id}]</span>
            <small>{item.filename || item.title || item.doc_id}</small>
          </header>
          <p>{item.text_preview || '无文本片段'}</p>

          {showScores ? (
            <footer>
              <small>doc_type: {item.doc_type || '-'}</small>
              <small>score: {item.score?.toFixed?.(4) ?? '-'}</small>
              {item.vector_score !== undefined ? <small>vector: {item.vector_score?.toFixed?.(4)}</small> : null}
              {item.graph_score !== undefined ? <small>graph: {item.graph_score?.toFixed?.(4)}</small> : null}
            </footer>
          ) : null}
        </article>
      ))}
    </div>
  );
}

export function SearchPanel() {
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [answerMd, setAnswerMd] = useState('');
  const [citations, setCitations] = useState<CitationItem[]>([]);
  const [hasStarted, setHasStarted] = useState(false);
  const [progressEvents, setProgressEvents] = useState<StreamProgressEvent[]>([]);
  const [currentStageMessage, setCurrentStageMessage] = useState('等待提问');
  const abortRef = useRef<AbortController | null>(null);

  const renderedHtml = useMemo(() => renderMarkdownToHtml(answerMd), [answerMd]);

  const onCitationRefClick = (event: ReactMouseEvent<HTMLElement>) => {
    const target = event.target as HTMLElement | null;
    const anchor = target?.closest('a.cite-ref') as HTMLAnchorElement | null;
    if (!anchor) return;

    const href = anchor.getAttribute('href') || '';
    if (!href.startsWith('#')) return;

    const targetId = href.slice(1);
    if (!targetId) return;

    const targetEl = document.getElementById(targetId);
    if (!targetEl) return;

    event.preventDefault();
    targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
    targetEl.classList.add('citation-target');
    window.setTimeout(() => {
      targetEl.classList.remove('citation-target');
    }, 1200);
  };

  const run = async () => {
    const cleanQuery = query.trim();
    if (!cleanQuery) {
      setError('请输入查询内容');
      return;
    }

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setHasStarted(true);
    setError('');
    setAnswerMd('');
    setCitations([]);
    setProgressEvents([]);
    setCurrentStageMessage('请求已发送，等待服务端响应');

    try {
      await streamAskWithLlm(
        cleanQuery,
        {
          retrievalMode: 'vector',
          useGraph: false
        },
        (chunk) => {
          setAnswerMd((prev) => prev + chunk);
        },
        (event) => {
          setProgressEvents((prev) => {
            const idx = prev.findIndex((item) => item.stage === event.stage);
            if (idx === -1) return [...prev, event];
            const next = [...prev];
            next[idx] = event;
            return next;
          });
          setCurrentStageMessage(event.message);
        },
        (items) => {
          setCitations(items);
        },
        controller.signal
      );
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        return;
      }
      setError(err instanceof Error ? err.message : '查询失败');
    } finally {
      setLoading(false);
    }
  };

  const stop = () => {
    abortRef.current?.abort();
    setLoading(false);
  };

  return (
    <section className="panel">
      <header className="panel-header">
        <h2>向量检索回答</h2>
      </header>

      <div className="form-grid">
        <label className="query-input">
          查询
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="例如：总结该制度的审批流程和风险点" />
        </label>
      </div>

      <div className="progress-board">
        <div className="progress-head">
          <strong>当前进度</strong>
          <span>{currentStageMessage}</span>
        </div>
        <div className="progress-steps">
          {(['intent', 'retrieval', 'generation'] as const).map((stage) => {
            const hit = progressEvents.find((item) => item.stage === stage);
            const stateClass = hit ? (hit.status === 'done' ? 'done' : 'running') : 'idle';
            return (
              <div key={stage} className={`progress-step ${stateClass}`}>
                <span>{STAGE_LABEL[stage]}</span>
                <small>{hit ? hit.message : '等待中'}</small>
              </div>
            );
          })}
        </div>
      </div>

      <div className="actions-row">
        <button onClick={run} disabled={loading}>{loading ? '回答生成中...' : '自动回答'}</button>
        <button className="secondary-btn" onClick={stop} disabled={!loading}>停止</button>
      </div>

      {error ? <p className="error-text">{error}</p> : null}

      {hasStarted ? (
        <div
          className="answer-box markdown-body"
          onClick={onCitationRefClick}
          dangerouslySetInnerHTML={{ __html: renderedHtml || '<p class="muted">等待回答...</p>' }}
        />
      ) : null}

      {hasStarted && citations.length > 0 ? (
        <div className="citation-board">
          <strong>引用来源</strong>
          <CitationList items={citations} keyPrefix="single" showScores useAnchorId anchorPrefix="" />
        </div>
      ) : null}
    </section>
  );
}
