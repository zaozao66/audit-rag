import { API_BASE, apiFetch, buildScopedHeaders, getCurrentKnowledgeScope } from './client';
import type {
  AskResponse,
  ClearAllDocumentsResponse,
  DeleteDocumentResponse,
  DocumentChunksResponse,
  DocumentDetailResponse,
  DocumentIdByFilenameResponse,
  DeleteStoredFileResponse,
  InfoResponse,
  ListStoredFilesResponse,
  ListDocumentsResponse,
  RegulationGroupOptions,
  RegulationGroupsResponse,
  RegulationGroupVersionsResponse,
  RegulationCompareResponse,
  SearchWithIntentResponse,
  CitationItem,
  StreamCitationsEvent,
  StreamProgressEvent,
  StreamSessionEvent,
  StatsResponse,
  UploadResponse,
  UploadStoredFilesResponse,
  RetrievalOptions
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
  regulationGroup?: RegulationGroupOptions;
}) {
  const form = new FormData();
  payload.files.forEach((file) => form.append('files', file));
  form.append('chunker_type', payload.chunkerType);
  form.append('doc_type', payload.docType);
  form.append('save_after_processing', String(payload.saveAfterProcessing ?? true));
  if (payload.title?.trim()) {
    form.append('title', payload.title.trim());
  }
  if (payload.regulationGroup?.enabled) {
    form.append('enable_regulation_group', 'true');
    if (payload.regulationGroup.groupId?.trim()) {
      form.append('regulation_group_id', payload.regulationGroup.groupId.trim());
    }
    if (payload.regulationGroup.groupName?.trim()) {
      form.append('regulation_group_name', payload.regulationGroup.groupName.trim());
    }
    if (payload.regulationGroup.versionLabel?.trim()) {
      form.append('version_label', payload.regulationGroup.versionLabel.trim());
    }
  }

  return apiFetch<UploadResponse>('/upload_store', {
    method: 'POST',
    body: form
  });
}

export function uploadArchive(payload: {
  archive: File;
  chunkerType: string;
  docType: string;
  title?: string;
  saveAfterProcessing?: boolean;
  regulationGroup?: RegulationGroupOptions;
}) {
  const form = new FormData();
  form.append('archive', payload.archive);
  form.append('chunker_type', payload.chunkerType);
  form.append('doc_type', payload.docType);
  form.append('save_after_processing', String(payload.saveAfterProcessing ?? true));
  if (payload.title?.trim()) {
    form.append('title', payload.title.trim());
  }
  if (payload.regulationGroup?.enabled) {
    form.append('enable_regulation_group', 'true');
    if (payload.regulationGroup.groupId?.trim()) {
      form.append('regulation_group_id', payload.regulationGroup.groupId.trim());
    }
    if (payload.regulationGroup.groupName?.trim()) {
      form.append('regulation_group_name', payload.regulationGroup.groupName.trim());
    }
    if (payload.regulationGroup.versionLabel?.trim()) {
      form.append('version_label', payload.regulationGroup.versionLabel.trim());
    }
  }

  return apiFetch<UploadResponse>('/upload_archive_store', {
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
  messages: Array<{ role: 'system' | 'user' | 'assistant'; content: string }>,
  options: Partial<RetrievalOptions> | undefined,
  sessionId: string | undefined,
  onDelta: (chunk: string) => void,
  onProgress?: (event: StreamProgressEvent) => void,
  onCitations?: (citations: CitationItem[]) => void,
  onSession?: (session: StreamSessionEvent) => void,
  signal?: AbortSignal
) {
  const payload = buildRetrievalPayload(options);
  const response = await fetch(`${API_BASE}/v1/chat/completions`, {
    method: 'POST',
    headers: buildScopedHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({
      messages,
      stream: true,
      session_id: sessionId,
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

      if (payload?.event === 'session') {
        onSession?.(payload as StreamSessionEvent);
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

export function listRegulationGroups(params?: { keyword?: string; includeDeleted?: boolean }) {
  const query = new URLSearchParams();
  if (params?.keyword?.trim()) query.set('keyword', params.keyword.trim());
  query.set('include_deleted', String(Boolean(params?.includeDeleted)));
  const suffix = query.toString() ? `?${query.toString()}` : '';
  return apiFetch<RegulationGroupsResponse>(`/regulation-groups${suffix}`);
}

export function listRegulationGroupVersions(groupId: string, includeDeleted = false) {
  const query = new URLSearchParams({ include_deleted: String(includeDeleted) });
  return apiFetch<RegulationGroupVersionsResponse>(
    `/regulation-groups/${encodeURIComponent(groupId)}/versions?${query.toString()}`
  );
}

export function compareRegulationVersions(payload: {
  leftDocId?: string;
  rightDocId?: string;
  groupId?: string;
  includeUnchanged?: boolean;
  keyword?: string;
  limit?: number;
}) {
  return apiFetch<RegulationCompareResponse>('/regulation-compare', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      left_doc_id: payload.leftDocId,
      right_doc_id: payload.rightDocId,
      group_id: payload.groupId,
      include_unchanged: payload.includeUnchanged ?? false,
      keyword: payload.keyword ?? '',
      limit: payload.limit ?? 500
    })
  });
}

export function getDocumentDetail(docId: string) {
  return apiFetch<DocumentDetailResponse>(`/documents/${encodeURIComponent(docId)}`);
}

export function getDocumentDetailByFilename(filename: string) {
  const query = new URLSearchParams({ filename });
  return apiFetch<DocumentDetailResponse>(`/documents/by-filename?${query.toString()}`);
}

export function getDocumentIdByFilename(filename: string, includeDeleted = false) {
  const query = new URLSearchParams({ filename, include_deleted: String(includeDeleted) });
  return apiFetch<DocumentIdByFilenameResponse>(`/documents/id-by-filename?${query.toString()}`);
}

export function getDocumentChunks(docId: string, includeText: boolean) {
  return apiFetch<DocumentChunksResponse>(
    `/documents/${encodeURIComponent(docId)}/chunks?include_text=${String(includeText)}`
  );
}

export function getDocumentRawUrl(docId: string) {
  const query = new URLSearchParams({ scope: getCurrentKnowledgeScope() });
  return `${API_BASE}/documents/${encodeURIComponent(docId)}/raw?${query.toString()}`;
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

export function uploadStoredFiles(payload: { files: File[]; scope?: string }) {
  const form = new FormData();
  payload.files.forEach((file) => form.append('files', file));
  if (payload.scope?.trim()) {
    form.append('domain', payload.scope.trim());
  }

  return apiFetch<UploadStoredFilesResponse>('/files/upload', {
    method: 'POST',
    headers: payload.scope?.trim()
      ? { 'X-Knowledge-Scope': payload.scope.trim().toLowerCase() }
      : undefined,
    body: form
  });
}

export function listStoredFiles(params?: {
  fileType?: string;
  keyword?: string;
  domain?: string;
  page?: number;
  pageSize?: number;
}) {
  const query = new URLSearchParams();
  if (params?.fileType?.trim()) query.set('file_type', params.fileType.trim());
  if (params?.keyword?.trim()) query.set('keyword', params.keyword.trim());
  if (params?.domain?.trim()) query.set('domain', params.domain.trim());
  query.set('page', String(params?.page ?? 1));
  query.set('page_size', String(params?.pageSize ?? 20));
  return apiFetch<ListStoredFilesResponse>(`/files?${query.toString()}`);
}

export function deleteStoredFile(fileId: string) {
  return apiFetch<DeleteStoredFileResponse>(`/files/${encodeURIComponent(fileId)}`, {
    method: 'DELETE'
  });
}

export function getStoredFileUrl(fileId: string) {
  return `${API_BASE}/files/${encodeURIComponent(fileId)}`;
}

export function getStoredFileByFilenameUrl(filename: string, domain?: string) {
  const query = new URLSearchParams({ filename });
  if (domain?.trim()) query.set('domain', domain.trim());
  return `${API_BASE}/files/by-filename?${query.toString()}`;
}

function buildRetrievalPayload(options?: Partial<RetrievalOptions>) {
  if (!options) return {};

  const payload: Record<string, unknown> = {};
  if (options.retrievalMode !== undefined) payload.retrieval_mode = options.retrievalMode;
  return payload;
}
