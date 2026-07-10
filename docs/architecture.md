# Архитектура — LYRA

Документ описывает компоненты системы, их ответственность, потоки данных (ingest и query), точки отказа и границу между MVP и target-архитектурой.

Связанные ADR: [ADR-001 (vector store)](adr/ADR-001-vector-store-pgvector-vs-qdrant.md), [ADR-005 (fusion)](adr/ADR-005-hybrid-search-fusion.md), [ADR-006 (LangGraph)](adr/ADR-006-langgraph-topology.md), [ADR-008 (очередь задач)](adr/ADR-008-task-queue-celery-vs-rq.md), [ADR-009 (LLM)](adr/ADR-009-llm-provider-abstraction.md), [ADR-010 (коннекторы)](adr/ADR-010-connector-architecture-mcp.md).

---

## 1. Обзор компонентов

```mermaid
flowchart LR
    subgraph Clients
        UI[React Chat UI]
        API_CLIENT[API-клиенты]
    end

    subgraph Backend["FastAPI (api)"]
        REST[REST API /api/v1]
        AUTH[Auth JWT + RBAC]
        RAG[LangGraph RAG Engine]
    end

    subgraph Workers["Celery workers"]
        INGEST[Ingest pipeline]
        SYNC[Connector sync beat]
        EVALW[Eval runner]
    end

    subgraph ML["ML-сервисы (self-hosted)"]
        OLLAMA[Ollama LLM]
        EMB[Embeddings bge-m3 TEI]
        RERANK[Reranker bge-reranker-v2-m3]
    end

    subgraph Storage
        PG[(PostgreSQL + pgvector)]
        REDIS[(Redis: cache + broker)]
        OBJ[(Файловое хранилище uploads)]
    end

    subgraph Sources
        FILES[Загрузка файлов]
        CONF[Confluence MCP-коннектор]
    end

    subgraph Observability
        PROM[Prometheus]
        GRAF[Grafana]
        LOGS[Структурные логи + LLM-трейсы]
    end

    UI --> REST
    API_CLIENT --> REST
    REST --> AUTH
    REST --> RAG
    RAG --> EMB
    RAG --> RERANK
    RAG --> OLLAMA
    RAG --> PG
    RAG --> REDIS
    REST -- job enqueue --> REDIS
    REDIS --> INGEST
    FILES --> REST
    CONF --> SYNC
    SYNC --> INGEST
    INGEST --> EMB
    INGEST --> PG
    INGEST --> OBJ
    EVALW --> RAG
    Backend --> LOGS
    Workers --> LOGS
    Backend --> PROM
    Workers --> PROM
    PROM --> GRAF
```

### Ответственность компонентов

| Компонент | Ответственность | Не отвечает за |
|-----------|-----------------|----------------|
| **React Chat UI** | Диалог, стриминг ответа, отображение цитат и confidence, фидбек, загрузка документов, статусы jobs | Бизнес-логику; вся логика на бэкенде |
| **FastAPI REST** | Контракт API, валидация (Pydantic v2), auth/RBAC, SSE-стриминг, постановка ingest-задач в очередь | Тяжёлую работу (парсинг, эмбеддинг) — всё в workers |
| **LangGraph RAG Engine** | Оркестрация query-пайплайна: retrieve → sufficiency → corrective → generate → cite → self-check; управление state | Хранение данных; доступ через репозитории |
| **Retrieval-слой** | Гибридный поиск (BM25 + вектор), RRF-fusion, вызов reranker, фильтры по метаданным; интерфейс `VectorStore` — точка миграции на Qdrant | Генерацию |
| **Celery workers** | Асинхронный ingest (parse/normalize/chunk/embed/index), периодическая синхронизация Confluence (beat), запуск evals | Обработку пользовательских запросов в реальном времени |
| **Коннекторы (`SourceConnector`)** | Получение и нормализация документов из источников, инкрементальность, идемпотентность | Chunking/embedding — общий пайплайн |
| **Ollama** | Инференс LLM (генерация, grading, query rewrite) | — |
| **Embeddings-сервис (TEI, bge-m3)** | Векторизация chunks и запросов | — |
| **Reranker-сервис** | Cross-encoder переранжирование top-N кандидатов | — |
| **PostgreSQL + pgvector** | Все реляционные данные + векторный индекс + full-text (tsvector) — единый источник истины MVP | — |
| **Redis** | Кэш (эмбеддинги запросов, ответы поиска), брокер Celery, rate limiting | Долговременное хранение |
| **Prometheus/Grafana/логи** | Метрики, дашборды, структурные логи, трейсинг LLM-вызовов | — |

---

## 2. Ingest-пайплайн

Всегда асинхронный (антипаттерн — синхронный ingest в HTTP-запросе). API только валидирует и ставит задачу.

```mermaid
flowchart TB
    subgraph Entry["Входные точки"]
        UPLOAD["POST /documents/upload"]
        BEAT["Celery beat: расписание синхронизации"]
    end

    UPLOAD -->|"сохранить файл, создать ingest_job(queued), вернуть job_id"| Q[(Redis broker)]
    BEAT --> SYNCTASK["connector.sync: list_changes()<br/>updated_at + content_hash"]
    SYNCTASK -->|на каждый изменённый документ| Q

    Q --> PARSE["parse: извлечение текста и структуры<br/>PDF/DOCX/MD/HTML(Confluence)"]
    PARSE --> NORM["normalize: единый DocumentIR<br/>заголовки, таблицы, код, метаданные"]
    NORM --> PII["PII/secret scan<br/>секрет найден → job failed_pii, не индексируем"]
    PII --> DEDUP{"content_hash<br/>уже в индексе?"}
    DEDUP -->|да| SKIP["job: skipped_duplicate"]
    DEDUP -->|нет| CHUNK["chunk: structure-aware разбиение<br/>ADR-002, context-management.md"]
    CHUNK --> EMBED["embed: батчами через bge-m3<br/>retry + rate limit"]
    EMBED --> INDEX["index: транзакция в PostgreSQL<br/>chunks + vector + tsvector + метаданные"]
    INDEX --> VERSION["активация версии: new version visible,<br/>прежняя версия — superseded"]
    VERSION --> DONE["job: completed + метрики"]

    PARSE -.->|ошибка| FAIL["job: failed + причина, retry с backoff"]
    EMBED -.->|ошибка| FAIL
```

Ключевые свойства:

- **Идемпотентность:** `content_hash` (SHA-256 нормализованного содержимого) проверяется до chunking; повторная загрузка — no-op (`skipped_duplicate`). Уникальный ключ `(source_id, external_id, content_hash)`.
- **Версионирование:** новая версия документа индексируется рядом со старой, затем атомарным UPDATE переключается видимость (`documents.active_version`); откат возможен. Старые chunks удаляются отложенно (garbage collection задачей).
- **Транзакционность:** chunks + векторы + tsvector пишутся в одной транзакции PostgreSQL — преимущество pgvector в MVP ([ADR-001](adr/ADR-001-vector-store-pgvector-vs-qdrant.md)).
- **Наблюдаемость:** каждый шаг обновляет `ingest_jobs.status`; метрики: длительность шага, размер очереди, ошибки по типам.

---

## 3. Query-пайплайн

```mermaid
flowchart TB
    Q["POST /chat (SSE)"] --> AUTHZ["Auth + RBAC<br/>(MVP: роль; задел: ACL-фильтр)"]
    AUTHZ --> CONDENSE["condense_question:<br/>история диалога → самостоятельный вопрос"]
    CONDENSE --> CACHE{"Redis: кэш<br/>retrieval-результата?"}
    CACHE -->|hit| GRAPH_IN
    CACHE -->|miss| HYBRID

    subgraph Retrieval["Retrieval-слой"]
        HYBRID["Параллельно:<br/>BM25 (tsvector, top-50)<br/>Vector (pgvector cosine, top-50)"]
        HYBRID --> RRF["RRF fusion, k=60 → top-50<br/>ADR-005"]
        RRF --> RER["Reranker bge-reranker-v2-m3<br/>top-50 → top-8"]
        RER --> DEDUP2["Дедупликация + MMR<br/>context-management.md"]
    end

    DEDUP2 --> GRAPH_IN

    subgraph LangGraph["LangGraph (ADR-006)"]
        GRAPH_IN["retrieve (результат retrieval в state)"] --> GRADE{"grade_sufficiency:<br/>контекст достаточен?"}
        GRADE -->|"да"| GEN["generate: ответ строго по контексту,<br/>inline-маркеры цитат, streaming"]
        GRADE -->|"нет, итераций < 2"| CORR["corrective_retrieve:<br/>query rewrite → повторный retrieval"]
        CORR --> GRADE
        GRADE -->|"нет, итерации исчерпаны"| REFUSE["honest_fallback:<br/>«в базе знаний не найдено»<br/>+ ближайшие документы"]
        GEN --> CITE["cite: маппинг маркеров [n] → chunks,<br/>валидация ссылок"]
        CITE --> SELF{"self_check:<br/>faithfulness ok?"}
        SELF -->|да| OUT["ответ + citations + confidence"]
        SELF -->|"нет, 1 retry"| GEN
        SELF -->|"нет повторно"| REFUSE
    end

    OUT --> SSE["SSE: токены → финальное событие<br/>(citations, confidence, trace_id)"]
    REFUSE --> SSE
    SSE --> AUDIT["Аудит-лог + LLM-трейс + метрики"]
```

Бюджет контекста, дедупликация и обработка длинных документов — [context-management.md](context-management.md). Формат ответа — [api-contract.md](api-contract.md).

---

## 4. Точки отказа и деградация

| Отказ | Поведение MVP | Production-цель |
|-------|---------------|-----------------|
| **Ollama недоступен / таймаут** | Честная ошибка 503 «модель недоступна» + retry с backoff на 1 повтор; никакой генерации без модели | Реплики инференса, failover на облачный API через `LLMClient` |
| **Embeddings-сервис недоступен** | Query: fallback на чистый BM25 с пометкой degraded в ответе; Ingest: retry, job остаётся queued | Реплики TEI, HPA |
| **Reranker недоступен** | Graceful degradation: используется RRF-порядок без reranking, флаг degraded в трейсе | Реплики |
| **Redis недоступен** | Кэш пропускается (запросы медленнее); Celery-задачи не принимаются — ingest временно недоступен, API отвечает 503 на upload | Redis Sentinel/кластер |
| **PostgreSQL недоступен** | Полный отказ (единый источник истины) — 503 | Managed PG / Patroni, реплики чтения |
| **Celery worker умер посреди задачи** | acks_late + идемпотентность шагов: задача перевыполняется без дубликатов | Autoscale workers, DLQ |
| **Confluence API недоступен/лимиты** | Синхронизация переносится на следующий тик beat; экспоненциальный backoff; алерт при N подряд неудач | — |
| **Переполнение контекста LLM** | Жёсткий бюджет токенов до вызова ([context-management.md](context-management.md)); усечение по приоритету rerank-score | — |
| **Провал self-check** | 1 регенерация → честный отказ; инцидент виден в метрике | Автоматический сбор таких случаев в eval-датасет |

---

## 5. Граница MVP vs Target

| Аспект | MVP (docker-compose) | Target (production) |
|--------|----------------------|---------------------|
| Векторное хранилище | pgvector в основной PG | Qdrant (критерии перехода в [ADR-001](adr/ADR-001-vector-store-pgvector-vs-qdrant.md)) |
| LLM | Ollama локально (Qwen2.5-instruct) | Облачный API (Claude/GPT) или GPU-кластер, за тем же `LLMClient` |
| Источники | Файлы + Confluence | + Notion, Google Drive, диски; каталог MCP-коннекторов |
| Доступ | JWT, RBAC на эндпоинты | SSO/OIDC, ACL на уровне документов при retrieval, аудит-экспорт |
| Тенантность | Один tenant (`tenant_id` в схеме) | Полная изоляция per-tenant (RLS / отдельные коллекции) |
| Развёртывание | docker-compose | Kubernetes, HPA для workers и ML-сервисов, Helm |
| Очередь | Celery + Redis, 1 worker | Пулы воркеров по типам задач, приоритетные очереди, DLQ |
| Retrieval | Hybrid + rerank | + граф-RAG, агентный мульти-source поиск, tuned fusion |
| Evals | Offline в CI | + Online-мониторинг качества, canary-промпты, автосбор датасета из фидбека |
| Наблюдаемость | Prometheus + Grafana + логи + LLM-трейсы | + OpenTelemetry end-to-end, алертинг, SLO-дашборды |

Роадмап перехода — [PLAN.md](../PLAN.md).
