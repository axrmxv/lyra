# Промпт фазы 3 — Retrieval: гибридный поиск, RRF, reranker

> Скопируй всё ниже в Claude Code. Предусловие: фазы 0–2 завершены (в БД есть проиндексированные chunks).

---

Проект **LYRA** — RAG-платформа корпоративных знаний. В этой фазе — retrieval-слой как самостоятельный, хорошо изолированный компонент. Прочитай перед началом: `docs/adr/ADR-001-vector-store-pgvector-vs-qdrant.md` (интерфейс VectorStore — точка будущей миграции на Qdrant), `docs/adr/ADR-004-reranker.md`, `docs/adr/ADR-005-hybrid-search-fusion.md`, `docs/context-management.md` §3, §7, `docs/api-contract.md` §3, `docs/security-and-access.md` §3 (точка врезки ACL).

## Жёсткие правила фазы
- Весь векторный доступ — только через интерфейс `VectorStore`; retrieval-код не знает про pgvector.
- Любой путь выдачи данных проходит через retrieval-слой (правило из security-and-access §3 — сюда позже врезается ACL-фильтр).
- Фильтры метаданных применяются в обоих каналах **до** ранжирования.

## Что реализовать (`lyra/retrieval/`)

1. **Интерфейсы** (`interfaces.py`): `VectorStore` (upsert_chunks, search(query_vector, filters, access_context, top_k), delete_by_document), `Fuser` (fuse(ranked_lists) -> ranked), `Reranker`, `Retriever` (фасад всего слоя). `access_context` — задел ACL: тип есть, в MVP «разрешено всё».
2. **PgVectorStore**: ANN-поиск cosine по HNSW; только активные версии (JOIN document_versions.status='active' — инвариант из `docs/data-model.md` §3); фильтры: collection_id, source_type, lang, source_id (по денормализованным колонкам и metadata GIN).
3. **BM25-канал** (`bm25.py`): tsvector-поиск (websearch_to_tsquery, ts_rank_cd), те же фильтры и видимость версий.
4. **HybridRetriever**: оба канала параллельно (asyncio.gather), top-50 каждый → `RRFFuser` (k=60, формула из ADR-005) → top-50.
5. **RerankerClient** (`lyra/core/clients/`): HTTP к TEI rerank (bge-reranker-v2-m3), батч 50 пар, таймаут 3 с; **graceful degradation**: недоступен/таймаут → RRF-порядок + флаг `degraded=true` (пробрасывается до API-ответа и в трейс). Порог отсечения по rerank-score (конфиг).
6. **Постобработка контекст-кандидатов** (`postprocess.py`, по `docs/context-management.md` §3): дедуп точных копий текста; MMR λ=0.7 по эмбеддингам кандидатов; склейка соседних chunks одного документа (ordinal подряд).
7. **Кэш Redis** (§7): embedding запроса (ключ sha256 нормализованного текста, TTL 24 ч), retrieval-результат после rerank (ключ sha256(query+collection+filters), TTL 15 мин). Redis недоступен → работать без кэша (не падать).
8. **API**: `POST /search` строго по `docs/api-contract.md` §3 — с разбивкой scores (bm25_rank, vector_rank, rrf, rerank), полем degraded и took_ms.
9. **Метрики Prometheus**: гистограммы латентности каждого шага (bm25, vector, fuse, rerank), hit-rate кэшей, счётчик degraded.

## Критерии приёмки
- /search находит: (а) запрос точным термином (имя конфига из документа) — BM25 вытягивает; (б) перефразированный запрос без общих слов — вектор вытягивает; оба присутствуют в fused-выдаче.
- `docker stop reranker` → /search отвечает с degraded=true, latency падает, ошибок нет.
- Повторный идентичный запрос — быстрее (кэш), метрика hit-rate растёт.

## Тесты
- Юнит (детерминированные, без БД): RRF на синтетических списках (проверка формулы и порядка), MMR (разнообразие отбирается), склейка соседей, ключи кэша.
- Интеграционные: PgVectorStore/BM25 на фикстурных chunks (посеять напрямую через ChunkRepo с фейковыми векторами); фильтры; невидимость superseded-версий; degradation-сценарий с недоступным reranker (мок httpx).
- Smoke-замер: 20 запросов подряд, вывести p50/p95 в отчёт фазы (сравнить с `docs/nfr.md` §1 /search).
