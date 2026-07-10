# Промпт фазы 2 — Асинхронный ingest-пайплайн и коннектор Confluence

> Скопируй всё ниже в Claude Code. Предусловие: фазы 0–1 завершены (схема БД и auth работают).

---

Проект **LYRA** — RAG-платформа корпоративных знаний. В этой фазе — весь путь документа от загрузки до проиндексированных chunks. Прочитай перед началом: `docs/architecture.md` §2 (диаграмма ingest — реализуй ровно её), `docs/adr/ADR-002-chunking-strategy.md`, `docs/adr/ADR-003-embedding-model.md`, `docs/adr/ADR-008-task-queue-celery-vs-rq.md`, `docs/adr/ADR-010-connector-architecture-mcp.md`, `docs/context-management.md` §1, §5, §6, `docs/data-model.md`, `docs/api-contract.md` §2, `docs/security-and-access.md` §5.

## Жёсткие правила фазы
- **Ingest только асинхронный**: HTTP-запрос сохраняет файл, создаёт ingest_job и ставит Celery-задачу; парсинг/эмбеддинг в API-процессе запрещён.
- **Идемпотентность**: каждый шаг переживает повторное выполнение (acks_late); повторная загрузка того же содержимого → `skipped_duplicate` по content_hash до эмбеддинга.
- **Версионирование**: обновлённый документ → новая document_version; переключение видимости атомарно (репозиторий из фазы 1).

## Что реализовать

1. **DocumentIR** (`lyra/ingest/ir.py`): промежуточное представление — дерево секций (headings) с блоками `paragraph | table | code | list` + метаданные документа. Все парсеры выдают его, chunker потребляет только его.
2. **Парсеры** (`lyra/ingest/parsers/`): PDF (pymupdf; выделение заголовков по эвристикам шрифтов, вырезание колонтитулов; при провале структуры — флаг low_structure), DOCX (python-docx, по стилям заголовков), Markdown (front-matter → метаданные), TXT, HTML-Confluence (storage format → IR, макросы → текст/таблицы).
3. **Chunker** (`lyra/ingest/chunker.py`): structure-aware по `docs/adr/ADR-002` с параметрами из `docs/context-management.md` §1 (таблица per source_type — это конфиг `collections.chunking_config`, не хардкод). Контекстный заголовок-префикс `{doc_title} > {headings_path}`. Токены считать токенайзером bge-m3 (huggingface tokenizers, локально). Таблицы/код — атомарно, правила split из §5–6. Детерминированность: одинаковый вход → одинаковые chunks.
4. **Secret-сканер** (`lyra/ingest/secrets_scan.py`): regex-паттерны из `docs/security-and-access.md` §5 (приватные ключи, AWS/GCP-ключи, ghp_/xoxb-/JWT-подобные токены, пароли в конфиг-строках). Находка → job `failed_pii`, документ не индексируется, аудит-запись.
5. **EmbeddingClient** (`lyra/ingest/embedding_client.py`): HTTP к TEI (bge-m3), батчи (размер — конфиг), retry с backoff, таймауты; используется и здесь, и в фазе 3 — вынеси в общий модуль `lyra/core/clients/`.
6. **Celery-задачи** (`lyra/workers/tasks/ingest.py`): цепочка parse → normalize → scan → dedup-check → chunk → embed → index → activate_version, статусы и таймстемпы шагов в `ingest_jobs.steps`; ретраи: сетевые ошибки — до 5 с exponential backoff+jitter; ошибки парсинга — permanent fail. `rate_limit` на embed-задаче.
7. **SourceConnector** (`lyra/ingest/connectors/`): Protocol из `docs/adr/ADR-010` (list_changes/fetch/normalize + SyncCursor); `UploadConnector` (вырожденный; у каждой коллекции ровно один неявный source типа `upload`, создаётся автоматически при первом upload — документы загрузок привязываются к нему); `ConfluenceConnector` (REST API, CQL lastModified-инкрементальность, пагинация, обработка удалений → status=deleted); beat-задача sync по `sources.sync_schedule`; токен — из env по `config.token_secret_ref`, в БД не хранится. MCP-обёртка: MCP-сервер с tools `list_spaces`, `search_pages`, `get_page`, использующий тот же коннектор-класс.
8. **API** (`docs/api-contract.md` §2, §6): `POST /documents/upload` (multipart, лимит 50 МБ, проверка типа по magic bytes, → 202 job_id), `GET /ingest/jobs/{id}`, `GET /ingest/jobs`, CRUD `/sources`, `POST /sources/{id}/sync`, `GET /documents`, `GET /documents/{id}` (метаданные + версии), `DELETE /documents/{id}`, `POST /admin/reindex` (admin, 202: новые версии всех документов коллекции, `ingest_jobs.kind=reindex`). Роли по api-contract.

## Критерии приёмки
- PDF 20+ страниц с таблицами: upload → job completed → chunks в БД с embedding, tsv, metadata (headings_path, block_type, lang); таблицы — атомарные chunks.
- Повторный upload того же файла → `skipped_duplicate`, число chunks не изменилось.
- Изменённый файл → version=2 active, chunks v1 невидимы (проверка через ChunkRepo).
- Файл с подложенным AWS-ключом → `failed_pii`, нет chunks.
- Confluence (мок-сервер или реальный тестовый space): первичный sync затем инкрементальный — только изменённые страницы; удаление страницы скрывает документ.
- Убить worker посреди job → повторный запуск завершает без дубликатов chunks.

## Тесты
- Юнит: chunker (детерминированность, размеры/overlap в токенах, атомарность таблиц/кода, префиксы), secret-сканер (позитив/негатив), парсеры на фикстурах (положи маленькие фикстуры PDF/DOCX/MD в tests/fixtures).
- Интеграционные: полный пайплайн на compose-стеке (можно с фейковым EmbeddingClient для скорости + один настоящий smoke), идемпотентность, версионирование, инкрементальный sync с мок-Confluence (respx/responses).
