import { API_BASE, apiFetch } from './client';
import type {
  AskResponse,
  ClearAllDocumentsResponse,
  DeleteDocumentResponse,
  DocumentChunksResponse,
  DocumentDetailResponse,
  InfoResponse,
  ListDocumentsResponse,
  SearchWithIntentResponse,
  CitationItem,
  StreamCitationsEvent,
  StreamProgressEvent,
  StatsResponse,
  UploadResponse,
  RetrievalOptions,
  RebuildGraphResponse,
  GraphEdgesResponse,
  GraphNodesResponse,
  GraphSubgraphResponse
} from '../types/rag';

export function getInfo() {
  return apiFetch<InfoResponse>('/info');
}

export function uploadFiles(payload: {
  files: File[];
  chunkerType: string;
  docType: string;
  title?: string;
  saveAfterProcessing?: boolean;
}) {
  const form = new FormData();
  payload.files.forEach((file) => form.append('files', file));
  form.append('chunker_type', payload.chunkerType);
  form.append('doc_type', payload.docType);
  form.append('save_after_processing', String(payload.saveAfterProcessing ?? true));
  if (payload.title?.trim()) {
    form.append('title', payload.title.trim());
  }

  return apiFetch<UploadResponse>('/upload_store', {
    method: 'POST',
    body: form
  });
}

export function searchWithIntent(query: string) {
  return apiFetch<SearchWithIntentResponse>('/search_with_intent', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query })
  });
}

export function askWithLlm(query: string, topK: number, options?: Partial<RetrievalOptions>) {
  const payload = buildRetrievalPayload(options);
  return apiFetch<AskResponse>('/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, top_k: topK, ...payload })
  });
}

export async function streamAskWithLlm(
  query: string,
  options: Partial<RetrievalOptions> | undefined,
  onDelta: (chunk: string) => void,
  onProgress?: (event: StreamProgressEvent) => void,
  onCitations?: (citations: CitationItem[]) => void,
  signal?: AbortSignal
) {
  const payload = buildRetrievalPayload(options);
  const response = await fetch(`${API_BASE}/v1/chat/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      messages: [{ role: 'user', content: query }],
      stream: true,
      ...payload
    }),
    signal
  });

  if (!response.ok) {
    let message = `请求失败 (${response.status})`;
    try {
      const data = (await response.json()) as { error?: { message?: string } };
      if (data?.error?.message) {
        message = data.error.message;
      }
    } catch {
      // ignore parse error and keep fallback message
    }
    throw new Error(message);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('流式响应不可用');
  }

  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r/g, '');

    let separatorIndex = buffer.indexOf('\n\n');
    while (separatorIndex !== -1) {
      const rawEvent = buffer.slice(0, separatorIndex);
      buffer = buffer.slice(separatorIndex + 2);

      const dataLines = rawEvent
        .split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trim());

      const payloadText = dataLines.join('');
      if (!payloadText) {
        separatorIndex = buffer.indexOf('\n\n');
        continue;
      }

      if (payloadText === '[DONE]') {
        return;
      }

      let payload: any;
      try {
        payload = JSON.parse(payloadText);
      } catch {
        separatorIndex = buffer.indexOf('\n\n');
        continue;
      }

      if (payload?.error?.message) {
        throw new Error(String(payload.error.message));
      }

      if (payload?.event === 'progress') {
        onProgress?.(payload as StreamProgressEvent);
      }

      if (payload?.event === 'citations') {
        onCitations?.((payload as StreamCitationsEvent).citations || []);
      }

      const delta = payload?.choices?.[0]?.delta?.content;
      if (delta) {
        onDelta(String(delta));
      }

      separatorIndex = buffer.indexOf('\n\n');
    }
  }
}

export function listDocuments(params: {
  docType?: string;
  keyword?: string;
  includeDeleted?: boolean;
}) {
  const query = new URLSearchParams();
  if (params.docType?.trim()) query.set('doc_type', params.docType.trim());
  if (params.keyword?.trim()) query.set('keyword', params.keyword.trim());
  query.set('include_deleted', String(Boolean(params.includeDeleted)));
  const suffix = query.toString() ? `?${query.toString()}` : '';

  return apiFetch<ListDocumentsResponse>(`/documents${suffix}`);
}

export function getDocumentDetail(docId: string) {
  return apiFetch<DocumentDetailResponse>(`/documents/${encodeURIComponent(docId)}`);
}

export function getDocumentChunks(docId: string, includeText: boolean) {
  return apiFetch<DocumentChunksResponse>(
    `/documents/${encodeURIComponent(docId)}/chunks?include_text=${String(includeText)}`
  );
}

export function deleteDocument(docId: string) {
  return apiFetch<DeleteDocumentResponse>(`/documents/${encodeURIComponent(docId)}`, {
    method: 'DELETE'
  });
}

export function clearAllDocuments() {
  return apiFetch<ClearAllDocumentsResponse>('/documents', {
    method: 'DELETE'
  });
}

export function getDocumentStats() {
  return apiFetch<StatsResponse>('/documents/stats');
}

export function rebuildGraphIndex() {
  return apiFetch<RebuildGraphResponse>('/graph/rebuild', {
    method: 'POST'
  });
}

export function getGraphNodes(params: {
  page?: number;
  pageSize?: number;
  nodeType?: string;
  keyword?: string;
}) {
  const query = new URLSearchParams();
  query.set('page', String(params.page ?? 1));
  query.set('page_size', String(params.pageSize ?? 20));
  if (params.nodeType?.trim()) query.set('node_type', params.nodeType.trim());
  if (params.keyword?.trim()) query.set('keyword', params.keyword.trim());
  return apiFetch<GraphNodesResponse>(`/graph/nodes?${query.toString()}`);
}

export function getGraphEdges(params: {
  page?: number;
  pageSize?: number;
  relation?: string;
  keyword?: string;
}) {
  const query = new URLSearchParams();
  query.set('page', String(params.page ?? 1));
  query.set('page_size', String(params.pageSize ?? 20));
  if (params.relation?.trim()) query.set('relation', params.relation.trim());
  if (params.keyword?.trim()) query.set('keyword', params.keyword.trim());
  return apiFetch<GraphEdgesResponse>(`/graph/edges?${query.toString()}`);
}

export function getGraphSubgraph(payload: {
  query?: string;
  nodeIds?: string[];
  hops?: number;
  maxNodes?: number;
}) {
  return apiFetch<GraphSubgraphResponse>('/graph/subgraph', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query: payload.query,
      node_ids: payload.nodeIds ?? [],
      hops: payload.hops ?? 2,
      max_nodes: payload.maxNodes ?? 120
    })
  });
}

function buildRetrievalPayload(options?: Partial<RetrievalOptions>) {
  if (!options) return {};

  const payload: Record<string, unknown> = {};
  if (options.retrievalMode !== undefined) payload.retrieval_mode = options.retrievalMode;
  if (options.useGraph !== undefined) payload.use_graph = options.useGraph;
  if (options.graphTopK !== undefined) payload.graph_top_k = options.graphTopK;
  if (options.graphHops !== undefined) payload.graph_hops = options.graphHops;
  if (options.hybridAlpha !== undefined) payload.hybrid_alpha = options.hybridAlpha;
  return payload;
}
