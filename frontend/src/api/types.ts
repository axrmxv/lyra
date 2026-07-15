// Типы API — вручную синхронизированы с docs/api-contract.md.
// Изменил контракт — обнови этот файл (и наоборот).

export type UserRole = 'viewer' | 'editor' | 'admin'

export interface ApiUser {
  id: string
  email: string
  role: UserRole
}

export interface LoginResponse {
  access_token: string
  token_type: string
  expires_in: number
  user: ApiUser
}

export interface ApiErrorBody {
  error: {
    code: string
    message: string
    details: Record<string, unknown>
  }
}

// --- Chat (§4) ---

export interface SessionCreateResponse {
  session_id: string
}

export interface ChatSessionItem {
  id: string
  title: string | null
  created_at: string
}

export interface SessionListResponse {
  items: ChatSessionItem[]
  total: number
}

export interface Citation {
  id: number
  chunk_id: string | null
  document_id: string | null
  document_title: string
  url: string | null
  quote: string
  relevance_score: number
}

export interface Confidence {
  label: 'high' | 'medium' | 'low'
  score: number
}

export interface Usage {
  llm_calls: number
  prompt_tokens: number
  completion_tokens: number
  took_ms: number
}

export interface NearestDocument {
  document_id: string
  title: string
  url: string | null
}

export interface ChatMessageItem {
  id: string
  role: 'user' | 'assistant'
  content: string
  confidence: Confidence | null
  refusal: boolean
  created_at: string
  citations: Citation[]
}

export interface MessageListResponse {
  items: ChatMessageItem[]
  total: number
}

// SSE-события POST /chat/sessions/{id}/messages
export type ChatStage =
  'retrieving' | 'grading' | 'corrective_retrieve' | 'generating' | 'self_check'

export interface StatusEvent {
  stage: ChatStage
}

export interface TokenEvent {
  text: string
}

export interface FinalEvent {
  message_id: string
  answer: string
  refusal: boolean
  citations: Citation[]
  confidence: Confidence
  degraded: boolean
  trace_id: string
  usage: Usage
  nearest_documents: NearestDocument[]
}

export interface ErrorEvent {
  code: string
  message: string
}

// --- Feedback (§5) ---

export type FeedbackRating = 'up' | 'down'

export interface FeedbackCreateRequest {
  message_id: string
  rating: FeedbackRating
  comment?: string
}

export interface FeedbackCreateResponse {
  id: string
}

// --- Ingest (§2) ---

export interface UploadResponse {
  job_id: string
  document_id: string
  status: string
}

export type IngestJobStatus =
  'queued' | 'processing' | 'completed' | 'failed' | 'failed_pii' | 'skipped_duplicate'

export interface IngestJob {
  id: string
  kind: 'upload' | 'sync' | 'reindex'
  status: IngestJobStatus
  steps: Record<string, unknown>
  error: string | null
  source_id: string | null
  document_version_id: string | null
  created_at: string
}

export interface IngestJobListResponse {
  items: IngestJob[]
  total: number
}

export interface DocumentItem {
  id: string
  source_id: string
  external_id: string
  title: string
  url: string | null
  author: string | null
  status: 'active' | 'deleted'
  active_version_id: string | null
  created_at: string
}

export interface DocumentListResponse {
  items: DocumentItem[]
  total: number
}

export type SourceType = 'upload' | 'confluence' | 'notion' | 'gdrive'

export interface SourceItem {
  id: string
  collection_id: string
  type: SourceType
  name: string
  config: Record<string, unknown>
  sync_schedule: string | null
  sync_cursor: Record<string, unknown> | null
  status: 'active' | 'paused' | 'error'
}

export interface SourceListResponse {
  items: SourceItem[]
  total: number
}

export interface SourceCreateRequest {
  collection_id: string
  type: 'confluence'
  name: string
  config: {
    base_url: string
    spaces: string[]
    token_secret_ref: string
  }
  sync_schedule?: string
}
