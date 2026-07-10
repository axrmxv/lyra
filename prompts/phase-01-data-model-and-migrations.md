# Промпт фазы 1 — Модель данных, миграции, auth/RBAC

> Скопируй всё ниже в Claude Code. Предусловие: фаза 0 завершена (скелет и compose работают).

---

Проект **LYRA** — RAG-платформа корпоративных знаний. В этой фазе — вся схема данных и базовая авторизация. Прочитай перед началом: `docs/data-model.md` (главный документ фазы), `docs/security-and-access.md` (§1, §2, §4), `docs/api-contract.md` (§1, §6), `docs/adr/ADR-001-vector-store-pgvector-vs-qdrant.md`.

## Задача
Реализовать модель данных из `docs/data-model.md` **целиком, включая заделы** (tenant_id везде, acl в metadata chunks, eval-таблицы), миграции Alembic, async-репозитории, JWT-auth и RBAC.

## Что реализовать

1. **SQLAlchemy 2.0 async модели** (`lyra/db/models/`): tenants, users, collections, sources, documents, document_versions, chunks, ingest_jobs, chat_sessions, messages, message_citations, feedback, eval_datasets, eval_items, eval_runs, eval_records — поля, enum'ы, связи и инварианты строго по `docs/data-model.md` §2–3. Общие миксины: id (uuid7), created_at/updated_at, tenant_id.
2. **Alembic:** начальная миграция: расширения `vector`, `citext`; все таблицы; индексы из `docs/data-model.md` §4 (HNSW по chunks.embedding vector_cosine_ops, GIN по tsv и metadata, уникальные ключи идемпотентности); `chunks.tsv` — GENERATED-колонка из text (конфигурация full-text: russian). Вторая миграция — seed: tenant «default», admin-пользователь (email/пароль из env), коллекция «default» (embedding_model=`BAAI/bge-m3`, chunking_config из `docs/context-management.md` §1). Downgrade обязателен. `alembic upgrade head` — в entrypoint api-контейнера.
3. **Репозитории** (`lyra/db/repositories/`): async, каждый метод принимает `tenant_id` (в MVP — константа из конфига; это задел мультитенантности из `docs/security-and-access.md` §4). Минимум: UserRepo, CollectionRepo, SourceRepo, DocumentRepo (включая транзакционное переключение active_version — инвариант из `docs/data-model.md` §3), ChunkRepo (bulk upsert; поиск добавит фаза 3), IngestJobRepo, ChatRepo.
4. **Auth** (`lyra/core/auth.py`): логин по email+паролю (argon2), JWT HS256 1 ч (`docs/security-and-access.md` §1); FastAPI-dependencies `current_user` и `require_role(min_role)`; иерархия viewer < editor < admin.
5. **Эндпоинты** (`docs/api-contract.md`): `POST /auth/login`, `GET /auth/me`, `GET/POST/PATCH /admin/users` (admin), `GET/POST/PATCH /admin/collections` (admin). Единый формат ошибок из преамбулы api-contract. Заголовок `X-Trace-Id` — middleware.

## Критерии приёмки
- Чистая БД → `alembic upgrade head` → `downgrade base` → `upgrade head` без ошибок.
- Логин seed-админом работает; JWT принимаются dependencies; истёкший токен → 401.
- Переключение версии документа атомарно (тест: конкурентные версии не дают двух active).

## Тесты (pytest, БД — testcontainers или compose-postgres)
- Репозитории: CRUD, уникальность `(document_id, content_hash)` и `(source_id, external_id)`, переключение active_version.
- **RBAC-матрица из `docs/security-and-access.md` §2 — параметризованный тест**: каждый эндпоинт × каждая роль; роль ниже минимальной → 403, без токена → 401.
- Auth: неверный пароль, деактивированный пользователь, протухший токен.

## Чего НЕ делать
Не включать enforcement ACL и RLS (только поля-заделы). Не писать поиск/ingest — фазы 2–3. Не хранить секреты источников в БД значениями (`docs/security-and-access.md` §5).
