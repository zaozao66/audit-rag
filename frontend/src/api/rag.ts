import { API_BASE, apiFetch, buildScopedHeaders, getCurrentKnowledgeScope } from './client';
import type {
  AskResponse,
  ClearAllDocumentsResponse,
  DeleteDocumentResponse,
  DocumentChunksResponse,
  DocumentDetailResponse,
  DocumentIdByFilenameResponse,
  DeleteStoredFileResponse,
  DeleteStoredFilesResponse,
  InfoResponse,
  ListStoredFilesResponse,
  ListDocumentsResponse,
  RegulationGroupOptions,
  RegulationGroupsResponse,
  RegulationGroupVersionsResponse,
  RegulationCompareResponse,
  SearchWithIntentResponse,
  CitationItem,
  StoredFileUploadProgress,
  StoredUploadSessionResponse,
  StreamCitationsEvent,
  StreamProgressEvent,
  StreamSessionEvent,
  StatsResponse,
  UploadResponse,
  UploadStoredFilesResponse,
  RetrievalOptions
} from '../types/rag';

const STORED_FILE_CHUNK_SIZE_BYTES = 8 * 1024 * 1024;

export function getInfo() {
  return apiFetch<InfoResponse>('/info');
}

export function uploadFiles(payload: {
  files: File[];
  chunkerType: string;
  docType?: string;
  title?: string;
  saveAfterProcessing?: boolean;
  searchable?: boolean;
  regulationGroup?: RegulationGroupOptions;
  knowledgeLabels?: Record<string, string[]>;
}) {
  const form = new FormData();
  payload.files.forEach((file) => form.append('files', file));
  form.append('chunker_type', payload.chunkerType);
  if (payload.docType?.trim()) {
    form.append('doc_type', payload.docType.trim());
  }
  form.append('save_after_processing', String(payload.saveAfterProcessing ?? true));
  form.append('searchable', String(payload.searchable ?? true));
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
  if (payload.knowledgeLabels && Object.keys(payload.knowledgeLabels).length > 0) {
    form.append('knowledge_labels', JSON.stringify(payload.knowledgeLabels));
  }

  return apiFetch<UploadResponse>('/upload_store', {
    method: 'POST',
    body: form
  });
}

export function uploadArchive(payload: {
  archive: File;
  chunkerType: string;
  docType?: string;
  title?: string;
  saveAfterProcessing?: boolean;
  searchable?: boolean;
  regulationGroup?: RegulationGroupOptions;
  knowledgeLabels?: Record<string, string[]>;
}) {
  const form = new FormData();
  form.append('archive', payload.archive);
  form.append('chunker_type', payload.chunkerType);
  if (payload.docType?.trim()) {
    form.append('doc_type', payload.docType.trim());
  }
  form.append('save_after_processing', String(payload.saveAfterProcessing ?? true));
  form.append('searchable', String(payload.searchable ?? true));
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
  if (payload.knowledgeLabels && Object.keys(payload.knowledgeLabels).length > 0) {
    form.append('knowledge_labels', JSON.stringify(payload.knowledgeLabels));
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
      stream_meta: true,
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

      const eventName = rawEvent
        .split('\n')
        .find((line) => line.startsWith('event:'))
        ?.slice(6)
        .trim();

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

      const payloadEvent = payload?.event || eventName;

      if (payloadEvent === 'progress') {
        onProgress?.(payload as StreamProgressEvent);
      }

      if (payloadEvent === 'citations') {
        onCitations?.((payload as StreamCitationsEvent).citations || []);
      }

      if (payloadEvent === 'session') {
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
  knowledgeFilters?: Record<string, string[]>;
}) {
  const query = new URLSearchParams();
  if (params.docType?.trim()) query.set('doc_type', params.docType.trim());
  if (params.keyword?.trim()) query.set('keyword', params.keyword.trim());
  if (params.knowledgeFilters && Object.keys(params.knowledgeFilters).length > 0) {
    query.set('knowledge_filters', JSON.stringify(params.knowledgeFilters));
  }
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

export function getDocumentChunks(docId: string, includeText: boolean, includeChunks = true) {
  return apiFetch<DocumentChunksResponse>(
    `/documents/${encodeURIComponent(docId)}/chunks?include_text=${String(includeText)}&include_chunks=${String(includeChunks)}`
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

export async function uploadStoredFiles(payload: {
  files: File[];
  scope?: string;
  onProgress?: (progress: StoredFileUploadProgress) => void;
}) {
  const records = [];
  const scope = payload.scope?.trim().toLowerCase();
  const totalFiles = payload.files.length;
  const overallBytes = payload.files.reduce((sum, file) => sum + Math.max(0, file.size || 0), 0);
  let completedBytes = 0;

  for (let fileIndex = 0; fileIndex < payload.files.length; fileIndex += 1) {
    const file = payload.files[fileIndex];
    const reportProgress = (uploadedBytes: number) => {
      const safeUploadedBytes = Math.max(0, Math.min(uploadedBytes, file.size || 0));
      const overallUploadedBytes = completedBytes + safeUploadedBytes;
      payload.onProgress?.({
        fileIndex,
        totalFiles,
        fileName: file.name,
        uploadedBytes: safeUploadedBytes,
        totalBytes: file.size || 0,
        overallUploadedBytes,
        overallBytes,
        percent: overallBytes > 0 ? Math.round((overallUploadedBytes / overallBytes) * 100) : 100
      });
    };

    reportProgress(0);
    const record = file.size > STORED_FILE_CHUNK_SIZE_BYTES
      ? await uploadStoredFileInChunks(file, scope, reportProgress)
      : await uploadStoredFileDirect(file, scope);
    completedBytes += file.size || 0;
    reportProgress(file.size || 0);
    records.push(record);
  }

  return {
    success: true,
    count: records.length,
    records
  } satisfies UploadStoredFilesResponse;
}

async function uploadStoredFileDirect(file: File, scope?: string) {
  const form = new FormData();
  form.append('files', file);
  if (scope) {
    form.append('domain', scope);
  }

  const response = await apiFetch<UploadStoredFilesResponse>('/files/upload', {
    method: 'POST',
    headers: scope ? { 'X-Knowledge-Scope': scope } : undefined,
    body: form
  });
  if (!response.records.length) {
    throw new Error('上传成功但未返回文件记录');
  }
  return response.records[0];
}

async function uploadStoredFileInChunks(
  file: File,
  scope: string | undefined,
  onProgress?: (uploadedBytes: number) => void
) {
  const totalChunks = Math.max(1, Math.ceil((file.size || 0) / STORED_FILE_CHUNK_SIZE_BYTES));
  const initResponse = await apiFetch<StoredUploadSessionResponse>('/files/upload/init', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(scope ? { 'X-Knowledge-Scope': scope } : {})
    },
    body: JSON.stringify({
      filename: file.name,
      file_size: file.size || 0,
      total_chunks: totalChunks,
      content_type: file.type || 'application/octet-stream',
      chunk_size: STORED_FILE_CHUNK_SIZE_BYTES,
      domain: scope
    })
  });

  const uploadId = initResponse.upload.upload_id;

  try {
    for (let chunkIndex = 0; chunkIndex < totalChunks; chunkIndex += 1) {
      const start = chunkIndex * STORED_FILE_CHUNK_SIZE_BYTES;
      const end = Math.min(start + STORED_FILE_CHUNK_SIZE_BYTES, file.size || 0);
      const chunk = file.slice(start, end);
      const form = new FormData();
      form.append('upload_id', uploadId);
      form.append('chunk_index', String(chunkIndex));
      form.append('chunk', chunk, `${file.name}.part${chunkIndex}`);

      await apiFetch<StoredUploadSessionResponse>('/files/upload/chunk', {
        method: 'POST',
        headers: scope ? { 'X-Knowledge-Scope': scope } : undefined,
        body: form
      });
      onProgress?.(end);
    }

    const completeResponse = await apiFetch<UploadStoredFilesResponse>('/files/upload/complete', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(scope ? { 'X-Knowledge-Scope': scope } : {})
      },
      body: JSON.stringify({ upload_id: uploadId })
    });
    if (!completeResponse.records.length) {
      throw new Error('分片上传完成但未返回文件记录');
    }
    return completeResponse.records[0];
  } catch (error) {
    try {
      await apiFetch<{ success: boolean; upload_id: string }>(`/files/upload/${encodeURIComponent(uploadId)}`, {
        method: 'DELETE',
        headers: scope ? { 'X-Knowledge-Scope': scope } : undefined
      });
    } catch {
      // Ignore abort failure and preserve the original error.
    }
    throw error;
  }
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

export function deleteStoredFiles(fileIds: string[]) {
  return apiFetch<DeleteStoredFilesResponse>('/files', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ file_ids: fileIds })
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
  if (options.knowledgeFilters && Object.keys(options.knowledgeFilters).length > 0) {
    payload.knowledge_filters = options.knowledgeFilters;
  }
  return payload;
}
