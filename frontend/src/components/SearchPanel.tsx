import { MessageOutlined, PauseCircleOutlined, PlayCircleOutlined, ReloadOutlined, SendOutlined, SoundOutlined, StopOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Empty, Input, Select, Space, Tag, Typography } from 'antd';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ChangeEvent, KeyboardEvent, MouseEvent as ReactMouseEvent } from 'react';
import { buildSpeechScript, synthesizeSpeech } from '../api/audio';
import { resolveApiUrl } from '../api/client';
import { streamAskWithLlm } from '../api/rag';
import { useSpeechPlayer } from '../hooks/useSpeechPlayer';
import type { MessageSpeechState, SpeechPlayState } from '../types/audio';
import type { CitationItem, ClassificationField, StreamProgressEvent } from '../types/rag';
import { renderMarkdownToHtml } from '../utils/markdown';

const { TextArea } = Input;

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

interface SearchPanelProps {
  scope: 'audit' | 'discipline';
  classificationFields: ClassificationField[];
}

function scopeLabel(scope: 'audit' | 'discipline') {
  return scope === 'audit' ? '审计' : '纪检';
}

function speechStateLabel(state: SpeechPlayState) {
  if (state === 'loading') return '语音生成中';
  if (state === 'playing') return '播放中';
  if (state === 'paused') return '已暂停';
  if (state === 'stopped') return '已停止';
  if (state === 'error') return '播放失败';
  return '未播报';
}

function buildKnowledgeFilters(fields: ClassificationField[], values: Record<string, string[]>) {
  const payload: Record<string, string[]> = {};
  fields.forEach((field) => {
    const current = (values[field.key] || []).map((item) => String(item || '').trim()).filter(Boolean);
    if (current.length > 0) {
      payload[field.key] = current;
    }
  });
  return payload;
}

export function SearchPanel({ scope, classificationFields }: SearchPanelProps) {
  const [sessionId, setSessionId] = useState(() => createSessionId());
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [progressText, setProgressText] = useState('等待提问');
  const [classificationValues, setClassificationValues] = useState<Record<string, string[]>>({});
  const [activeCitation, setActiveCitation] = useState<ActiveCitationState | null>(null);
  const [speechStates, setSpeechStates] = useState<Record<string, MessageSpeechState>>({});
  const [chatItems, setChatItems] = useState<ChatItem[]>([
    {
      id: createMessageId(),
      role: 'assistant',
      content: `你好，当前在${scopeLabel(scope)}知识域，我会结合该域知识库回答。你可以连续追问，我会保留上下文。`,
      citations: []
    }
  ]);

  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const updateSpeechState = useCallback((messageId: string, patch: Partial<MessageSpeechState>) => {
    setSpeechStates((prev) => ({
      ...prev,
      [messageId]: (() => {
        const current = prev[messageId];
        const nextState = patch.state || current?.state || 'idle';
        return {
          ...(current || {}),
          ...patch,
          state: nextState,
        };
      })(),
    }));
  }, []);

  const onSpeechPlayerStateChange = useCallback((messageId: string, state: SpeechPlayState, playbackError?: string) => {
    updateSpeechState(messageId, {
      state,
      error: playbackError || (state === 'error' ? '音频播放失败' : undefined),
    });
  }, [updateSpeechState]);

  const speechPlayer = useSpeechPlayer(onSpeechPlayerStateChange);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [chatItems, loading]);

  useEffect(() => {
    setClassificationValues((prev) => {
      const next: Record<string, string[]> = {};
      classificationFields.forEach((field) => {
        next[field.key] = prev[field.key] || [];
      });
      return next;
    });
  }, [classificationFields]);

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

    speechPlayer.stopAll();
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
      const knowledgeFilters = buildKnowledgeFilters(classificationFields, classificationValues);
      await streamAskWithLlm(
        payloadMessages,
        {
          retrievalMode: 'vector',
          knowledgeFilters,
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

  const playSpeech = async (item: ChatItem) => {
    const content = item.content.trim();
    if (!content) return;

    const currentState = speechStates[item.id];
    if (currentState?.audioUrl) {
      await speechPlayer.playFromUrl(item.id, currentState.audioUrl, true);
      return;
    }

    updateSpeechState(item.id, { state: 'loading', error: undefined });

    try {
      const script = await buildSpeechScript({
        text: content,
        style: 'brief',
        sessionId,
        messageId: item.id,
      });
      const speechText = script.speech_text.trim();
      updateSpeechState(item.id, { speechText });

      const audio = await synthesizeSpeech({
        input: speechText,
        sessionId,
        messageId: item.id,
      });

      const audioUrl = resolveApiUrl(audio.audio_url);
      updateSpeechState(item.id, {
        audioId: audio.id,
        audioUrl,
      });
      await speechPlayer.playFromUrl(item.id, audioUrl, true);
    } catch (err) {
      const message = err instanceof Error ? err.message : '语音播报失败';
      updateSpeechState(item.id, { state: 'error', error: message });
    }
  };

  const replaySpeech = async (item: ChatItem) => {
    const speechState = speechStates[item.id];
    if (speechState?.audioUrl) {
      await speechPlayer.playFromUrl(item.id, speechState.audioUrl, true);
      return;
    }
    await playSpeech(item);
  };

  const pauseSpeech = (messageId: string) => {
    speechPlayer.pause(messageId);
  };

  const resumeSpeech = async (messageId: string) => {
    try {
      await speechPlayer.resume(messageId);
    } catch (err) {
      const message = err instanceof Error ? err.message : '继续播放失败';
      updateSpeechState(messageId, { state: 'error', error: message });
    }
  };

  const stopSpeech = (messageId: string) => {
    speechPlayer.stop(messageId);
  };

  const resetSession = () => {
    abortRef.current?.abort();
    speechPlayer.stopAll();
    setLoading(false);
    setError('');
    setProgressText('已创建新会话');
    setSessionId(createSessionId());
    setSpeechStates({});
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
    <Card className="app-card chat-panel" title="多轮检索对话" extra={
      <Button icon={<ReloadOutlined />} onClick={resetSession} disabled={loading}>新会话</Button>
    }>
      <Space direction="vertical" style={{ width: '100%' }} size={8}>
        <Typography.Text type="secondary">{progressText}</Typography.Text>
        <Typography.Text type="secondary">知识域: <Typography.Text code>{scopeLabel(scope)}</Typography.Text></Typography.Text>
        {classificationFields.length > 0 ? (
          <Space wrap size={[12, 8]}>
            <Typography.Text type="secondary">检索范围</Typography.Text>
            {classificationFields.map((field) => (
              <Select
                key={field.key}
                mode={field.multiple ? 'multiple' : undefined}
                allowClear
                style={{ minWidth: 220 }}
                value={field.multiple ? (classificationValues[field.key] || []) : (classificationValues[field.key]?.[0] || undefined)}
                onChange={(value) => {
                  const nextValues = Array.isArray(value) ? value : (value ? [String(value)] : []);
                  setClassificationValues((prev) => ({
                    ...prev,
                    [field.key]: nextValues,
                  }));
                }}
                options={field.options.map((option) => ({ value: option.value, label: option.label }))}
                placeholder={`${field.label}（默认全部）`}
              />
            ))}
          </Space>
        ) : null}
        <Typography.Text type="secondary">会话ID: <Typography.Text code>{sessionId}</Typography.Text></Typography.Text>
        {error ? <Alert type="error" showIcon message={error} /> : null}
      </Space>

      <div className={`chat-body ${activeCitation ? 'has-citation' : ''}`}>
        <div className="chat-thread" ref={scrollRef} onClick={onCitationRefClick}>
          {chatItems.map((item) => {
            const anchorPrefix = `${item.id}-`;
            const html = renderMarkdownToHtml(item.content || (item.role === 'assistant' ? '...' : ''), {
              citationAnchorPrefix: anchorPrefix
            });
            const speechState = speechStates[item.id] || { state: 'idle' };
            const canPlaySpeech = item.role === 'assistant' && Boolean(item.content.trim());
            const canPause = speechState.state === 'playing';
            const canResume = speechState.state === 'paused';
            const canStopSpeech = speechState.state === 'loading' || speechState.state === 'playing' || speechState.state === 'paused';

            return (
              <article key={item.id} className={`chat-bubble ${item.role}`}>
                <div className="chat-role">{item.role === 'user' ? '你' : '助手'}</div>
                <div className="chat-content markdown-body" dangerouslySetInnerHTML={{ __html: html }} />
                {item.role === 'assistant' ? (
                  <div className="chat-speech">
                    <Space size={8} wrap className="chat-speech-controls">
                      <Button
                        size="small"
                        icon={<SoundOutlined />}
                        onClick={() => void playSpeech(item)}
                        loading={speechState.state === 'loading'}
                        disabled={!canPlaySpeech || speechState.state === 'playing'}
                      >
                        播报
                      </Button>
                      <Button
                        size="small"
                        icon={<PauseCircleOutlined />}
                        onClick={() => pauseSpeech(item.id)}
                        disabled={!canPause}
                      >
                        暂停
                      </Button>
                      <Button
                        size="small"
                        icon={<PlayCircleOutlined />}
                        onClick={() => void resumeSpeech(item.id)}
                        disabled={!canResume}
                      >
                        继续
                      </Button>
                      <Button
                        size="small"
                        icon={<StopOutlined />}
                        onClick={() => stopSpeech(item.id)}
                        disabled={!canStopSpeech}
                      >
                        停止播报
                      </Button>
                      <Button
                        size="small"
                        onClick={() => void replaySpeech(item)}
                        disabled={!canPlaySpeech}
                      >
                        重播
                      </Button>
                    </Space>
                    <Typography.Text type="secondary" className="chat-speech-status">
                      播报状态: {speechStateLabel(speechState.state)}
                    </Typography.Text>
                    {speechState.error ? (
                      <Typography.Text type="danger" className="chat-speech-error">{speechState.error}</Typography.Text>
                    ) : null}
                  </div>
                ) : null}
                {item.progress ? <Typography.Text type="secondary" className="chat-progress">{item.progress}</Typography.Text> : null}
                {item.error ? <Alert type="error" showIcon message={item.error} /> : null}
                {item.role === 'assistant' && item.citations.length > 0 ? (
                  <div className="chat-citations">
                    <div className="chat-citation-tags">
                      {item.citations.map((citation) => {
                        const isActive = activeCitation?.messageId === item.id && activeCitation?.citation.source_id === citation.source_id;
                        return (
                          <Tag
                            key={`${item.id}-${citation.source_id}`}
                            color={isActive ? 'processing' : 'default'}
                            className="citation-tag"
                            onClick={() => {
                              openCitation(item.id, citation.source_id);
                            }}
                          >
                            [{citation.source_id}]
                          </Tag>
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
            <Card size="small" className="chat-citation-card" title={`引用 ${activeCitation.citation.source_id}`} extra={
              <Button size="small" onClick={() => setActiveCitation(null)}>关闭</Button>
            }>
              <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
                {activeCitation.citation.filename || activeCitation.citation.title || activeCitation.citation.doc_id}
              </Typography.Paragraph>
              <Typography.Paragraph>{activeCitation.citation.text_preview || '无文本片段'}</Typography.Paragraph>
            </Card>
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="点击文中引用标记或来源标签，在此查看详情" />
          )}
        </aside>
      </div>

      <div className="chat-input-area">
        <TextArea
          value={query}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setQuery(e.target.value)}
          placeholder="请输入问题，支持连续追问..."
          autoSize={{ minRows: 3, maxRows: 8 }}
          onKeyDown={(event: KeyboardEvent<HTMLTextAreaElement>) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              void send();
            }
          }}
        />
        <Space>
          <Button type="primary" icon={<SendOutlined />} onClick={() => void send()} disabled={loading || !query.trim()}>
            {loading ? '回答生成中...' : '发送'}
          </Button>
          <Button icon={<StopOutlined />} onClick={stop} disabled={!loading}>停止</Button>
          <Button icon={<MessageOutlined />} onClick={resetSession} disabled={loading}>重置会话</Button>
        </Space>
      </div>
    </Card>
  );
}
