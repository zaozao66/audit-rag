export type ChunkerType = 'smart' | 'regulation' | 'audit_report' | 'audit_issue' | 'default';

export interface ApiError {
  error: string;
}

export interface UploadResponse {
  success: boolean;
  message: string;
  file_count: number;
  processed_count: number;
  skipped_count?: number;
  updated_count?: number;
  total_chunks?: number;
  chunker_used: string;
}

export interface SearchResultItem {
  score: number;
  original_score?: number;
  text: string;
  doc_id: string;
  filename: string;
  file_type: string;
  doc_type: string;
  title: string;
}

export interface SearchWithIntentResponse {
  success: boolean;
  query: string;
  intent: string;
  intent_reason: string;
  suggested_top_k: number;
  results: SearchResultItem[];
}

export interface AskResponse {
  success: boolean;
  query: string;
  intent: string;
  answer: string;
  search_results: SearchResultItem[];
  llm_usage: Record<string, number>;
  model: string;
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
  avg_chunk_size: number;
  chunks: DocumentChunkItem[];
}

export interface DocumentChunksResponse {
  success: boolean;
  data: DocumentChunksData;
}

export interface DocumentDetailResponse {
  success: boolean;
  document: DocumentRecord & { chunks?: DocumentChunkItem[] };
}

export interface DeleteDocumentResponse {
  success: boolean;
  doc_id: string;
  removed_chunks: number;
  error?: string;
}

export interface ClearAllDocumentsResponse {
  success: boolean;
  removed_documents: number;
  removed_active_documents: number;
  removed_deleted_documents: number;
  removed_vector_files: number;
  error?: string;
}

export interface StatsResponse {
  success: boolean;
  stats: DocumentStats;
}
