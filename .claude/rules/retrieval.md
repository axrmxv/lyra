---
description: Правила для retrieval-слоя (VectorStore, гибридный поиск, rerank)
paths:
  - "backend/lyra/retrieval/**"
---

# Правила: retrieval-слой (`lyra/retrieval/`)

- Векторный доступ — только через интерфейс `VectorStore` (`docs/adr/ADR-001`); упоминание pgvector/SQL допустимо только внутри `PgVectorStore`. Это точка миграции на Qdrant — не размывать.
- Схема слияния — RRF k=60 (`docs/adr/ADR-005`); смена стратегии fusion — через реализацию интерфейса `Fuser` + ADR, не правкой формулы на месте.
- Фильтры метаданных и `access_context` применяются в ОБОИХ каналах (BM25 и вектор) **до** ранжирования — пост-фильтрация после rerank запрещена (утечка через top-k, см. `docs/security-and-access.md` §3).
- Видимость данных: только chunks активных версий (`document_versions.status='active'`) — инвариант `docs/data-model.md` §3; проверяется тестом на superseded-версии.
- Reranker обязан деградировать gracefully (таймаут 3 с → RRF-порядок + `degraded=true`); исключение из reranker не должно ронять запрос.
- `access_context` — задел ACL: параметр не удалять, даже пока он «разрешено всё».
- Redis недоступен → слой работает без кэша, не падает. Ключи кэша при появлении ACL/tenant обязаны включать их в ключ.
- Тесты RRF/MMR — детерминированные, без БД и сети; изменения параметров retrieval (top-k, пороги, λ MMR) → `make eval` до PR.
