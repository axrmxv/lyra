// HTTP-клиент API: единая обработка ошибок контракта и SSE-стрим чата.
// Токен — только в памяти (setAccessToken из auth-контекста).

import type {
  ApiErrorBody,
  DocumentListResponse,
  ErrorEvent,
  FeedbackCreateRequest,
  FeedbackCreateResponse,
  FinalEvent,
  IngestJobListResponse,
  LoginResponse,
  MessageListResponse,
  SessionCreateResponse,
  SessionListResponse,
  SourceCreateRequest,
  SourceItem,
  SourceListResponse,
  StatusEvent,
  TokenEvent,
  UploadResponse,
  ApiUser,
} from './types'

const API_BASE = '/api/v1'

let accessToken: string | null = null

export function setAccessToken(token: string | null): void {
  accessToken = token
}

export class ApiError extends Error {
  readonly code: string
  readonly status: number

  constructor(status: number, code: string, message: string) {
    super(message)
    this.code = code
    this.status = status
  }
}

function isApiErrorBody(value: unknown): value is ApiErrorBody {
  if (typeof value !== 'object' || value === null || !('error' in value)) return false
  const error: unknown = (value as { error: unknown }).error
  return (
    typeof error === 'object' &&
    error !== null &&
    'code' in error &&
    'message' in error &&
    typeof (error as { code: unknown }).code === 'string' &&
    typeof (error as { message: unknown }).message === 'string'
  )
}

async function toApiError(response: Response): Promise<ApiError> {
  let body: unknown = null
  try {
    body = await response.json()
  } catch {
    // не-JSON тело — генерируем ошибку по статусу ниже
  }
  if (isApiErrorBody(body)) {
    return new ApiError(response.status, body.error.code, body.error.message)
  }
  return new ApiError(response.status, `http_${response.status}`, 'Ошибка запроса к API')
}

function authHeaders(): Record<string, string> {
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {}
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...authHeaders(),
      ...(init.headers ?? {}),
    },
  })
  if (!response.ok) throw await toApiError(response)
  if (response.status === 204) {
    // 204 — тела нет; вызывающий код типизирует как void
    return undefined as T
  }
  return (await response.json()) as T
}

// --- Auth ---

export function login(email: string, password: string): Promise<LoginResponse> {
  return request('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) })
}

export function me(): Promise<ApiUser> {
  return request('/auth/me')
}

// --- Chat ---

export function createSession(): Promise<SessionCreateResponse> {
  return request('/chat/sessions', { method: 'POST' })
}

export function listSessions(): Promise<SessionListResponse> {
  return request('/chat/sessions')
}

export function listMessages(sessionId: string): Promise<MessageListResponse> {
  return request(`/chat/sessions/${sessionId}/messages`)
}

export type ChatStreamEvent =
  | { type: 'status'; data: StatusEvent }
  | { type: 'token'; data: TokenEvent }
  | { type: 'final'; data: FinalEvent }
  | { type: 'error'; data: ErrorEvent }

function parseSseBlock(block: string): ChatStreamEvent | null {
  let eventName = ''
  let dataLine = ''
  for (const line of block.split('\n')) {
    if (line.startsWith('event: ')) eventName = line.slice('event: '.length).trim()
    else if (line.startsWith('data: ')) dataLine = line.slice('data: '.length)
  }
  if (!eventName || !dataLine) return null
  let data: unknown
  try {
    data = JSON.parse(dataLine)
  } catch {
    return null
  }
  if (
    eventName === 'status' ||
    eventName === 'token' ||
    eventName === 'final' ||
    eventName === 'error'
  ) {
    // Тип данных гарантирован контрактом api-contract §4 по имени события
    return { type: eventName, data } as ChatStreamEvent
  }
  return null
}

export async function streamChatMessage(
  sessionId: string,
  content: string,
  onEvent: (event: ChatStreamEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE}/chat/sessions/${sessionId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ content }),
    signal,
  })
  if (!response.ok) throw await toApiError(response)
  if (!response.body) throw new ApiError(0, 'stream_unavailable', 'Стриминг не поддерживается')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let separatorIndex = buffer.indexOf('\n\n')
    while (separatorIndex >= 0) {
      const block = buffer.slice(0, separatorIndex)
      buffer = buffer.slice(separatorIndex + 2)
      const event = parseSseBlock(block)
      if (event) onEvent(event)
      separatorIndex = buffer.indexOf('\n\n')
    }
  }
}

// --- Feedback ---

export function sendFeedback(body: FeedbackCreateRequest): Promise<FeedbackCreateResponse> {
  return request('/feedback', { method: 'POST', body: JSON.stringify(body) })
}

// --- Documents / ingest ---

export function listDocuments(): Promise<DocumentListResponse> {
  return request('/documents')
}

export function deleteDocument(documentId: string): Promise<void> {
  return request(`/documents/${documentId}`, { method: 'DELETE' })
}

export function uploadDocument(file: File, collectionId: string): Promise<UploadResponse> {
  const form = new FormData()
  form.append('file', file)
  form.append('collection_id', collectionId)
  return request('/documents/upload', { method: 'POST', body: form })
}

export function listJobs(): Promise<IngestJobListResponse> {
  return request('/ingest/jobs')
}

// --- Sources ---

export function listSources(): Promise<SourceListResponse> {
  return request('/sources')
}

export function createSource(body: SourceCreateRequest): Promise<SourceItem> {
  return request('/sources', { method: 'POST', body: JSON.stringify(body) })
}

export function syncSource(sourceId: string): Promise<{ source_id: string; status: string }> {
  return request(`/sources/${sourceId}/sync`, { method: 'POST' })
}
