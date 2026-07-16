# API-контракт — LYRA

REST API FastAPI, префикс `/api/v1`. Все схемы — Pydantic v2, OpenAPI генерируется автоматически (этот документ — источник требований, OpenAPI — производный артефакт).

**Общие правила**
- Аутентификация: `Authorization: Bearer <JWT>`. Роли: `viewer` ≤ `editor` ≤ `admin`; минимальная роль указана у каждого эндпоинта.
- Ошибки — единый формат: `{"error": {"code": "string", "message": "string", "details": {}}}`, HTTP-коды: 400 валидация, 401/403 доступ, 404, 409 конфликт, 422 семантика, 429 rate limit, 503 деградация (LLM/зависимость недоступна).
- 429 всегда несёт заголовок `Retry-After` (секунды); коды: `rate_limited` (лимит запросов: /chat — per-user, /auth/login — per-IP), `overloaded` (заняты все слоты одновременных генераций LLM).
- Все ответы содержат заголовок `X-Trace-Id`.
- Пагинация: `?limit=&offset=`, ответ `{"items": [...], "total": int}`.

---

## 1. Auth

### POST /auth/login — публичный
```json
// req
{"email": "user@corp.ru", "password": "..."}
// 200
{"access_token": "jwt", "token_type": "bearer", "expires_in": 3600,
 "user": {"id": "uuid", "email": "...", "role": "viewer"}}
```

### GET /auth/me — viewer
Возвращает текущего пользователя.

## 2. Ingest

### POST /documents/upload — editor
`multipart/form-data`: `file` (PDF/DOCX/MD/TXT, ≤50 МБ), `collection_id`.
Документ привязывается к неявному source типа `upload` коллекции (создаётся автоматически при первом upload; у каждой коллекции ровно один upload-source).
Синхронно только сохраняет файл и ставит задачу (FR-2):
```json
// 202
{"job_id": "uuid", "document_id": "uuid", "status": "queued"}
```
Ошибки: 413 (размер), 415 (тип файла), 503 (брокер недоступен).

### GET /ingest/jobs/{job_id} — editor
```json
// 200
{"job_id": "uuid", "kind": "upload", "status": "processing",
 "steps": {"parse": {"status": "completed", "duration_ms": 812},
           "chunk": {"status": "processing"}},
 "document": {"id": "uuid", "title": "...", "version": 3},
 "error": null}
```
`status`: `queued | processing | completed | failed | failed_pii | skipped_duplicate` ([data-model.md](data-model.md)).

### GET /ingest/jobs — editor
Список с фильтрами `?status=&source_id=`.

### Sources — editor (создание/изменение), viewer (чтение)
- `GET /sources`, `POST /sources`, `GET /sources/{id}`, `PATCH /sources/{id}`, `DELETE /sources/{id}`
- `POST /sources/{id}/sync` — 202, ручной запуск синхронизации (иначе by beat-расписанию)
```json
// POST /sources req (Confluence)
{"collection_id": "uuid", "type": "confluence", "name": "Confluence DEV",
 "config": {"base_url": "https://corp.atlassian.net/wiki", "spaces": ["DEV", "HR"],
            "token_secret_ref": "CONFLUENCE_TOKEN"},
 "sync_schedule": "0 * * * *"}
```
Секрет передаётся ссылкой на env-переменную, не значением ([security-and-access.md](security-and-access.md)).

### Documents — viewer (чтение), editor (удаление)
- `GET /documents?collection_id=&source_id=&q=` — список с метаданными и версией.
- `GET /documents/{id}` — метаданные + список версий.
- `DELETE /documents/{id}` — soft delete, chunks исключаются из выдачи.

## 3. Search (raw retrieval, UC-9)

### POST /search — viewer
Поиск без генерации: гибрид + RRF + rerank, отражает retrieval-слой как есть.
```json
// req
{"query": "как настроить VPN", "collection_id": "uuid",
 "top_k": 10,
 "filters": {"source_type": ["confluence"], "lang": "ru"},
 "rerank": true}
// 200
{"results": [
  {"chunk_id": "uuid", "text": "...", "score": 0.91,
   "scores": {"bm25_rank": 2, "vector_rank": 1, "rrf": 0.032, "rerank": 0.91},
   "document": {"id": "uuid", "title": "VPN для сотрудников", "url": "https://...",
                "headings_path": ["ИТ", "Удалённый доступ"], "source_updated_at": "2026-06-01T10:00:00Z"}}
 ],
 "degraded": false, "took_ms": 420}
```

## 4. Chat (UC-1..3)

### POST /chat/sessions — viewer
Создать сессию → `{"session_id": "uuid"}`.

### GET /chat/sessions / GET /chat/sessions/{id}/messages — viewer
История своих сессий (чужая сессия → 403, несуществующая → 404).

```json
// GET /chat/sessions → 200
{"items": [{"id": "uuid", "title": "Сколько дней отпуска?", "created_at": "..."}], "total": 1}
// GET /chat/sessions/{id}/messages → 200
{"items": [
  {"id": "uuid", "role": "user", "content": "...", "confidence": null,
   "refusal": false, "created_at": "...", "citations": []},
  {"id": "uuid", "role": "assistant", "content": "... [1]",
   "confidence": {"label": "high", "score": 0.87}, "refusal": false, "created_at": "...",
   "citations": [{"id": 1, "chunk_id": "uuid", "document_id": "uuid",
                  "document_title": "...", "url": "...", "quote": "...",
                  "relevance_score": 0.93}]}
 ], "total": 2}
```
`refusal` — признак честного отказа (для отдельного рендера в истории); после GC-чистки chunks `chunk_id`/метаданные цитаты могут быть null, quote сохраняется.

### POST /chat/sessions/{id}/messages — viewer, **SSE**
```json
// req
{"content": "Сколько дней отпуска в первый год?", "collection_id": "uuid"}
```
Ответ `text/event-stream`, события по порядку:

| event | data | Когда |
|-------|------|-------|
| `status` | `{"stage": "retrieving" \| "grading" \| "corrective_retrieve" \| "generating" \| "self_check"}` | смена узла графа — прогресс в UI |
| `token` | `{"text": "..."}` | стриминг токенов ответа (с маркерами [n] как есть) |
| `final` | см. ниже | всегда последнее |
| `error` | `{"code": "llm_unavailable", "message": "..."}` | вместо final при сбое |

```json
// event: final
{"message_id": "uuid",
 "answer": "В первый год предоставляется 28 дней отпуска [1]. Заявление подаётся за две недели [2].",
 "refusal": false,
 "citations": [
   {"id": 1, "chunk_id": "uuid", "document_id": "uuid",
    "document_title": "Политика отпусков", "url": "https://corp.atlassian.net/wiki/...",
    "quote": "Сотрудникам в первый год работы предоставляется 28 календарных дней отпуска.",
    "relevance_score": 0.93},
   {"id": 2, "chunk_id": "uuid", "document_id": "uuid",
    "document_title": "Политика отпусков", "url": "https://...", "quote": "...", "relevance_score": 0.88}
 ],
 "confidence": {"label": "high", "score": 0.87},
 "degraded": false,
 "trace_id": "tr_01H...",
 "usage": {"llm_calls": 4, "prompt_tokens": 6120, "completion_tokens": 214, "took_ms": 9400}}
```

**Честный отказ** (FR-9): `refusal: true`, `answer` — текст отказа, `citations: []`, `confidence.label: "low"`, дополнительно `nearest_documents: [{document_id, title, url}]`.

Семантика полей ([ADR-007](adr/ADR-007-citation-strategy.md)): маркеры `[n]` в `answer` ссылаются на `citations[].id`; `confidence.score` — агрегат sufficiency, rerank-score и self-check; `degraded: true` — reranker/кэш были недоступны, качество может быть ниже.

## 5. Feedback (UC-7)

### POST /feedback — viewer
```json
// req
{"message_id": "uuid", "rating": "down", "comment": "ответ про старую версию политики"}
// 201
{"id": "uuid"}
```

### GET /feedback — admin
Фильтры `?rating=&from=&to=`, для разбора и пополнения eval-датасета.

## 6. Admin

- `GET/POST/PATCH /admin/collections` — admin. Управление коллекциями (embedding_model, chunking_config).
- `GET/POST/PATCH /admin/users` — admin. CRUD пользователей и ролей.
- `POST /admin/reindex` — admin, 202: `{"collection_id": "uuid"}` — переиндексация (новые версии всех документов).
- `POST /admin/eval-runs` — admin, 202: `{"dataset_id": "uuid"}` → `{"run_id": "uuid"}` (задача в очереди `evals`). Аддитивно: вместо `dataset_id` можно передать `dataset_name` (дефолт `golden`) и `judge` (`local|cloud`).
- `GET /admin/eval-runs/{id}` — admin: статус, агрегаты метрик, сравнение с baseline-run:
```json
{"run_id": "uuid", "status": "completed", "git_ref": "abc123",
 "metrics": {"faithfulness": 0.88, "answer_relevance": 0.83,
             "context_precision": 0.74, "context_recall": 0.79,
             "citation_validity": 0.97, "honest_refusal_rate": 0.92},
 "baseline": {"run_id": "uuid", "delta": {"faithfulness": +0.02}},
 "failed_items": [{"item_id": "uuid", "question": "...", "faithfulness": 0.4}]}
```

## 7. Служебные

- `GET /health` — публичный: liveness.
- `GET /health/ready` — readiness: PG, Redis, Ollama, embeddings, reranker (по каждому: up/down).
- `GET /metrics` — Prometheus (внутренняя сеть).

## 8. Версионирование API

`/api/v1` фиксирован для MVP; ломающие изменения → `/api/v2`. Аддитивные изменения (новые поля ответа) не считаются ломающими — клиенты обязаны игнорировать неизвестные поля.
