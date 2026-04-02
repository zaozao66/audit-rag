export type ChunkerType = 'smart' | 'regulation' | 'technical_standard' | 'audit_report' | 'audit_issue' | 'default';

export interface ApiError {
  error: string;
}

export interface ClassificationOption {
  value: string;
  label: string;
}

export interface ClassificationField {
  key: string;
  label: string;
  required?: boolean;
  multiple?: boolean;
  options: ClassificationOption[];
}

export interface UploadResponse {
  success: boolean;
  message: string;
  file_count: number;
  archive_name?: string;
  extracted_count?: number;
  unsupported_files?: string[];
  failed_files?: Array<{ filename: string; error: string }>;
  processed_count: number;
  skipped_count?: number;
  updated_count?: number;
  total_chunks?: number;
  chunker_used: string;
}

export interface RegulationGroupOptions {
  enabled?: boolean;
  groupId?: string;
  groupName?: string;
  versionLabel?: string;
}

export interface SearchResultItem {
  score: number;
  original_score?: number;
  vector_score?: number;
  graph_score?: number;
  text: string;
  doc_id: string;
  chunk_id?: string;
  filename: string;
  file_type: string;
  doc_type: string;
  title: string;
}

export interface CitationItem {
  source_id: string;
  doc_id: string;
  chunk_id: string;
  filename: string;
  title: string;
  doc_type: string;
  score: number;
  original_score?: number;
  vector_score?: number;
  graph_score?: number;
  text_preview: string;
  page_nos: number[];
  header: string;
  section_path: string[];
  knowledge_labels?: Record<string, string[]>;
}

export interface SearchWithIntentResponse {
  success: boolean;
  query: string;
  intent: string;
  intent_reason: string;
  suggested_top_k: number;
  retrieval_mode?: RetrievalMode;
  results: SearchResultItem[];
}

export interface AskResponse {
  success: boolean;
  query: string;
  intent: string;
  answer: string;
  search_results: SearchResultItem[];
  citations?: CitationItem[];
  llm_usage: Record<string, number>;
  model: string;
  retrieval_mode?: RetrievalMode;
}

export interface StreamProgressEvent {
  event: 'progress';
  stage: 'intent' | 'retrieval' | 'generation';
  status: 'running' | 'done';
  message: string;
  intent?: string;
  top_k?: number;
  use_rerank?: boolean;
  hits?: number;
  model?: string;
  session_id?: string;
  standalone_query?: string;
  route_reason?: string;
}

export interface StreamCitationsEvent {
  event: 'citations';
  citations: CitationItem[];
}

export interface StreamSessionEvent {
  event: 'session';
  session_id: string;
  summary?: string;
  scope?: string;
}

export interface DocumentStats {
  total_documents: number;
  active_documents: number;
  deleted_documents: number;
  total_chunks: number;
  total_size_bytes: number;
  total_size_mb: number;
  by_type: Record<string, { count: number; chunks: number }>;
}

export interface InfoResponse {
  status: string;
  scope?: string;
  classification_fields?: ClassificationField[];
  vector_store_status: string;
  vector_count: number;
  dimension: number;
  chunker_type: string;
  embedding_model: string;
  rerank_enabled: boolean;
  document_stats: DocumentStats;
}

export type RetrievalMode = 'vector' | 'graph' | 'hybrid';

export interface RetrievalOptions {
  retrievalMode: RetrievalMode;
  knowledgeFilters?: Record<string, string[]>;
}

export interface DocumentRecord {
  doc_id: string;
  filename: string;
  content_hash: string;
  file_path: string;
  file_size: number;
  doc_type: string;
  upload_time: string;
  chunk_count: number;
  status: 'active' | 'deleted';
  searchable: boolean;
  version: number;
  tags: string[];
  knowledge_labels?: Record<string, string[]>;
  regulation_group_id: string;
  regulation_group_name: string;
  version_label: string;
}

export interface ListDocumentsResponse {
  success: boolean;
  count: number;
  documents: DocumentRecord[];
}

export interface RegulationGroupItem {
  group_id: string;
  group_name: string;
  version_count: number;
  latest_upload_time: string;
  latest_doc_id: string;
  latest_filename: string;
}

export interface RegulationGroupsResponse {
  success: boolean;
  count: number;
  groups: RegulationGroupItem[];
}

export interface RegulationGroupVersionsResponse {
  success: boolean;
  group_id: string;
  count: number;
  versions: DocumentRecord[];
}

export interface RegulationCompareItem {
  article_key: string;
  article_no: string;
  article_number?: number;
  status: 'added' | 'removed' | 'modified' | 'unchanged';
  old_text: string;
  new_text: string;
  old_page_nos: number[];
  new_page_nos: number[];
  old_chunk_ids: string[];
  new_chunk_ids: string[];
  metrics?: {
    similarity: number;
    added_chars: number;
    removed_chars: number;
    replaced_chars: number;
  } | null;
}

export interface RegulationCompareResult {
  left_document: DocumentRecord;
  right_document: DocumentRecord;
  summary: {
    added: number;
    removed: number;
    modified: number;
    unchanged: number;
    total_articles: number;
  };
  diffs: RegulationCompareItem[];
  filtered_count: number;
  returned_count: number;
  truncated: boolean;
  include_unchanged: boolean;
  keyword: string;
}

export interface RegulationCompareResponse {
  success: boolean;
  data: RegulationCompareResult;
}

export interface DocumentChunkItem {
  chunk_index: number;
  chunk_id: string;
  global_index?: number;
  text?: string;
  text_preview: string;
  char_count: number;
  line_start?: number;
  line_end?: number;
  metadata: {
    filename: string;
    doc_type: string;
    page_nos: number[];
    header: string;
    section_path: string[];
    semantic_boundary: string;
    knowledge_labels?: Record<string, string[]>;
  };
}

export interface DocumentCatalogItem {
  id: string;
  title: string;
  display_title?: string;
  preview_text?: string;
  node_type?: string;
  level: number;
  line_no: number;
  page_no?: number | null;
  chunk_id: string;
  section_path: string[];
}

export interface DocumentChunksData {
  doc_id: string;
  filename: string;
  doc_type: string;
  upload_time: string;
  chunk_count: number;
  total_chars: number;
  total_lines?: number;
  full_text_source?: 'stored_full_text' | 'reloaded_file' | 'chunk_fallback' | 'missing_full_text' | string;
  catalog: DocumentCatalogItem[];
  full_text_lines: string[];
  chunks: DocumentChunkItem[];
}

export interface DocumentDetailData {
  doc_id: string;
  filename: string;
  doc_type: string;
  file_size: number;
  upload_time: string;
  chunk_count: number;
  status: 'active' | 'deleted';
  version: number;
  tags: string[];
  knowledge_labels?: Record<string, string[]>;
  regulation_group_id: string;
  regulation_group_name: string;
  version_label: string;
}

export interface DocumentDetailResponse {
  success: boolean;
  document: DocumentDetailData;
}

export interface DocumentIdByFilenameResponse {
  success: boolean;
  data: {
    filename: string;
    doc_id: string;
    upload_time: string;
    status: 'active' | 'deleted' | string;
    matched_count: number;
    candidates: Array<{
      doc_id: string;
      upload_time: string;
      status: 'active' | 'deleted' | string;
    }>;
  };
}

export interface DocumentChunksResponse {
  success: boolean;
  data: DocumentChunksData;
}

export interface DeleteDocumentResponse {
  success: boolean;
  message: string;
  doc_id: string;
}

export interface ClearAllDocumentsResponse {
  success: boolean;
  message: string;
  deleted_documents?: number;
  deleted_chunks?: number;
  error?: string;
}

export interface StatsResponse {
  success: boolean;
  stats: DocumentStats;
}

export interface StoredFileRecord {
  domain: string;
  file_id: string;
  original_filename: string;
  file_type: string;
  upload_time: string;
  storage_key: string;
  file_size: number;
  storage_type: 'local' | 'minio' | string;
}

export interface ListStoredFilesResponse {
  success: boolean;
  page: number;
  page_size: number;
  total: number;
  items: StoredFileRecord[];
}

export interface DeleteStoredFileResponse {
  success: boolean;
  file_id: string;
  original_filename: string;
}

export interface DeleteStoredFilesResponse {
  success: boolean;
  requested_count: number;
  deleted_count: number;
  failed_count: number;
  deleted: Array<{
    success: boolean;
    file_id: string;
    original_filename: string;
  }>;
  failed: Array<{
    file_id: string;
    error: string;
  }>;
}

export interface UploadStoredFilesResponse {
  success: boolean;
  count: number;
  records: StoredFileRecord[];
}

export interface StoredUploadSessionInfo {
  upload_id: string;
  domain: string;
  original_filename: string;
  content_type: string;
  file_size: number;
  total_chunks: number;
  chunk_size: number;
  created_at: string;
  updated_at: string;
  uploaded_chunk_count: number;
  completed: boolean;
  missing_chunks: number[];
}

export interface StoredUploadSessionResponse {
  success: boolean;
  upload: StoredUploadSessionInfo;
}

export interface StoredFileUploadProgress {
  fileIndex: number;
  totalFiles: number;
  fileName: string;
  uploadedBytes: number;
  totalBytes: number;
  overallUploadedBytes: number;
  overallBytes: number;
  percent: number;
}
