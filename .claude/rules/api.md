---
description: Правила для API-слоя и ingest-задач
paths:
  - "backend/lyra/api/**"
  - "backend/lyra/ingest/**"
  - "backend/lyra/workers/**"
---

# Правила: API и ingest (`lyra/api/`, `lyra/ingest/`, `lyra/workers/`)

## API
- Контракт — `docs/api-contract.md`; ломающие изменения `/api/v1` запрещены, только аддитивные (§8). Новое поле ответа — обнови api-contract.md в том же PR.
- Каждый новый эндпоинт: dependency `require_role(...)` + строка в RBAC-матрице `docs/security-and-access.md` §2 + параметризованный тест матрицы. Эндпоинт без auth — только /health*, /metrics, /auth/login.
- Единый формат ошибок и `X-Trace-Id` — из преамбулы api-contract; не изобретать локальные форматы.
- В API-процессе не бывает: парсинга документов, эмбеддинга, вызовов LLM вне RAG-графа. Тяжёлое → Celery.

## Ingest / workers
- Ingest асинхронный: HTTP-обработчик только сохраняет файл, создаёт `ingest_job`, ставит задачу — и всё.
- Каждая Celery-задача идемпотентна (переживает повтор при acks_late): upsert по ключам, `content_hash`-проверка до эмбеддинга, атомарное переключение версий.
- Ошибки парсинга — permanent fail (без retry); сетевые ошибки — retry с exponential backoff + jitter, max 5.
- Secret-сканер перед индексацией не отключать и не ослаблять паттерны; находка → `failed_pii`, не «индексировать с предупреждением».
- Секреты коннекторов — только `token_secret_ref` на env-переменную; значение токена не логировать и не сохранять в БД.
- Новый источник = реализация `SourceConnector` (`docs/adr/ADR-010`); логика синхронизации/идемпотентности не копируется в задачи.
