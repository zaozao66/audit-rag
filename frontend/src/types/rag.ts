export type ChunkerType = 'smart' | 'regulation' | 'audit_report' | 'audit_issue' | 'default';

export interface ApiError {
  error: string;
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
  version: number;
  tags: string[];
}

export interface ListDocumentsResponse {
  success: boolean;
  count: number;
  documents: DocumentRecord[];
}

export interface DocumentChunkItem {
  chunk_index: number;
  chunk_id: string;
  text?: string;
  text_preview: string;
  char_count: number;
  metadata: {
    filename: string;
    doc_type: string;
    page_nos: number[];
    header: string;
    section_path: string[];
  };
}

export interface DocumentChunksData {
  doc_id: string;
  filename: string;
  doc_type: string;
  upload_time: string;
  chunk_count: number;
  total_chars: number;
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
}

export interface DocumentDetailResponse {
  success: boolean;
  document: DocumentDetailData;
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
