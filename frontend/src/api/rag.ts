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
  StreamProgressEvent,
  StatsResponse,
  UploadResponse
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

export function askWithLlm(query: string, topK: number) {
  return apiFetch<AskResponse>('/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, top_k: topK })
  });
}

export async function streamAskWithLlm(
  query: string,
  onDelta: (chunk: string) => void,
  onProgress?: (event: StreamProgressEvent) => void,
  signal?: AbortSignal
) {
  const response = await fetch(`${API_BASE}/v1/chat/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      messages: [{ role: 'user', content: query }],
      stream: true
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
