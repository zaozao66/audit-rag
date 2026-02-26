import { useEffect, useMemo, useRef, useState } from 'react';
import type { MouseEvent as ReactMouseEvent } from 'react';
import { streamAskWithLlm } from '../api/rag';
import type { CitationItem, StreamProgressEvent } from '../types/rag';
import { renderMarkdownToHtml } from '../utils/markdown';

function createSessionId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function createMessageId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

interface ChatItem {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  citations: CitationItem[];
  progress?: string;
  error?: string;
}

interface ActiveCitationState {
  messageId: string;
  citation: CitationItem;
}

export function SearchPanel() {
  const [sessionId, setSessionId] = useState(() => createSessionId());
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [progressText, setProgressText] = useState('等待提问');
  const [activeCitation, setActiveCitation] = useState<ActiveCitationState | null>(null);
  const [chatItems, setChatItems] = useState<ChatItem[]>([
    {
      id: createMessageId(),
      role: 'assistant',
      content: '你好，我会结合知识库回答。你可以连续追问，我会保留上下文。',
      citations: []
    }
  ]);

  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [chatItems, loading]);

  const apiMessages = useMemo(
    () =>
      chatItems.map((item) => ({
        role: item.role,
        content: item.content
      })),
    [chatItems]
  );

  const updateAssistantItem = (assistantId: string, updater: (item: ChatItem) => ChatItem) => {
    setChatItems((prev) => prev.map((item) => (item.id === assistantId ? updater(item) : item)));
  };

  const openCitation = (messageId: string, sourceId: string) => {
    const msg = chatItems.find((item) => item.id === messageId);
    if (!msg) return;
    const hit = msg.citations.find((citation) => citation.source_id === sourceId);
    if (!hit) return;
    setActiveCitation({ messageId, citation: hit });
  };

  const onCitationRefClick = (event: ReactMouseEvent<HTMLElement>) => {
    const target = event.target as HTMLElement | null;
    const anchor = target?.closest('a.cite-ref') as HTMLAnchorElement | null;
    if (!anchor) return;

    const href = anchor.getAttribute('href') || '';
    if (!href.startsWith('#')) return;

    const targetId = href.slice(1);
    event.preventDefault();
    const marker = '-cite-';
    const idx = targetId.lastIndexOf(marker);
    if (idx <= 0) return;

    const messageId = targetId.slice(0, idx);
    const sourceId = targetId.slice(idx + marker.length);
    if (!messageId || !sourceId) return;
    openCitation(messageId, sourceId);
  };

  const send = async () => {
    const cleanQuery = query.trim();
    if (!cleanQuery || loading) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const userId = createMessageId();
    const assistantId = createMessageId();

    setError('');
    setQuery('');
    setLoading(true);
    setProgressText('请求已发送，等待响应');

    const nextUserItem: ChatItem = {
      id: userId,
      role: 'user',
      content: cleanQuery,
      citations: []
    };

    const nextAssistantItem: ChatItem = {
      id: assistantId,
      role: 'assistant',
      content: '',
      citations: [],
      progress: '思考中...'
    };

    const payloadMessages = [
      ...apiMessages,
      { role: 'user' as const, content: cleanQuery }
    ];

    setChatItems((prev) => [...prev, nextUserItem, nextAssistantItem]);

    try {
      await streamAskWithLlm(
        payloadMessages,
        {
          retrievalMode: 'vector',
          useGraph: false
        },
        sessionId,
        (chunk) => {
          updateAssistantItem(assistantId, (item) => ({ ...item, content: item.content + chunk }));
        },
        (event: StreamProgressEvent) => {
          setProgressText(event.message);
          updateAssistantItem(assistantId, (item) => ({ ...item, progress: event.message }));
        },
        (items) => {
          updateAssistantItem(assistantId, (item) => ({ ...item, citations: items }));
        },
        (sessionEvent) => {
          if (sessionEvent.session_id) {
            setSessionId(sessionEvent.session_id);
          }
        },
        controller.signal
      );
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        updateAssistantItem(assistantId, (item) => ({ ...item, progress: '已停止' }));
        return;
      }
      const msg = err instanceof Error ? err.message : '查询失败';
      setError(msg);
      updateAssistantItem(assistantId, (item) => ({ ...item, error: msg, progress: '失败' }));
    } finally {
      updateAssistantItem(assistantId, (item) => ({ ...item, progress: undefined }));
      setLoading(false);
    }
  };

  const stop = () => {
    abortRef.current?.abort();
    setLoading(false);
  };

  const resetSession = () => {
    abortRef.current?.abort();
    setLoading(false);
    setError('');
    setProgressText('已创建新会话');
    setSessionId(createSessionId());
    setChatItems([
      {
        id: createMessageId(),
        role: 'assistant',
        content: '已开启新会话，你可以继续提问。',
        citations: []
      }
    ]);
    setActiveCitation(null);
  };

  return (
    <section className="panel chat-panel">
      <header className="panel-header chat-header">
        <div>
          <h2>多轮检索对话</h2>
          <p className="muted">{progressText}</p>
        </div>
        <div className="actions-row no-margin">
          <button className="secondary-btn" onClick={resetSession} disabled={loading}>新会话</button>
        </div>
      </header>

      <div className="chat-session-meta muted">
        会话ID: <code>{sessionId}</code>
      </div>

      <div className={`chat-body ${activeCitation ? 'has-citation' : ''}`}>
        <div className="chat-thread" ref={scrollRef} onClick={onCitationRefClick}>
          {chatItems.map((item) => {
            const anchorPrefix = `${item.id}-`;
            const html = renderMarkdownToHtml(item.content || (item.role === 'assistant' ? '...' : ''), {
              citationAnchorPrefix: anchorPrefix
            });

            return (
              <article key={item.id} className={`chat-bubble ${item.role}`}>
                <div className="chat-role">{item.role === 'user' ? '你' : '助手'}</div>
                <div className="chat-content markdown-body" dangerouslySetInnerHTML={{ __html: html }} />
                {item.progress ? <p className="muted chat-progress">{item.progress}</p> : null}
                {item.error ? <p className="error-text">{item.error}</p> : null}
                {item.role === 'assistant' && item.citations.length > 0 ? (
                  <div className="chat-citations">
                    <div className="chat-citation-tags">
                      {item.citations.map((citation) => {
                        const isActive =
                          activeCitation?.messageId === item.id &&
                          activeCitation?.citation.source_id === citation.source_id;
                        return (
                          <button
                            key={`${item.id}-${citation.source_id}`}
                            type="button"
                            className={`chip ${isActive ? 'active' : ''}`}
                            onClick={() => {
                              openCitation(item.id, citation.source_id);
                            }}
                          >
                            [{citation.source_id}]
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>

        <aside className={`chat-citation-panel ${activeCitation ? 'open' : ''}`}>
          {activeCitation ? (
            <div className="chat-citation-card">
              <div className="chat-citation-card-head">
                <strong>引用 {activeCitation.citation.source_id}</strong>
                <button type="button" className="secondary-btn" onClick={() => setActiveCitation(null)}>关闭</button>
              </div>
              <p className="muted">
                {activeCitation.citation.filename || activeCitation.citation.title || activeCitation.citation.doc_id}
              </p>
              <p>{activeCitation.citation.text_preview || '无文本片段'}</p>
            </div>
          ) : (
            <div className="chat-citation-empty muted">点击文中引用标记或来源标签，在此查看详情</div>
          )}
        </aside>
      </div>

      <div className="chat-input-area">
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="请输入问题，支持连续追问..."
          rows={3}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              void send();
            }
          }}
        />
        <div className="actions-row no-margin">
          <button onClick={() => void send()} disabled={loading || !query.trim()}>{loading ? '回答生成中...' : '发送'}</button>
          <button className="secondary-btn" onClick={stop} disabled={!loading}>停止</button>
        </div>
      </div>

      {error ? <p className="error-text">{error}</p> : null}
    </section>
  );
}
