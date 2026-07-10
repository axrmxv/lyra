# Промпт фазы 0 — Скаффолдинг и инфраструктура разработки

> Скопируй всё ниже в Claude Code, находясь в корне репозитория LYRA.

---

Ты работаешь над проектом **LYRA** — RAG-платформой корпоративных знаний (FastAPI + LangGraph + PostgreSQL/pgvector + Redis + Celery + React/Vite/TS, всё локально в docker-compose, LLM — Ollama). Прочитай перед началом: `docs/architecture.md`, `docs/nfr.md` (§5, §6), `PLAN.md` (фаза 0), а также правила `.claude/rules/python.md`, `.claude/rules/typescript.md`, `.claude/rules/git.md` — создаваемые в этой фазе конфиги (ruff, mypy, eslint, prettier, tsconfig, pre-commit) обязаны соответствовать этим правилам (strict-режимы, запрет `any` — правилами линтеров, не договорённостью).

## Задача
Создай скелет монорепозитория: всё запускается, ничего содержательного ещё не делает.

## Что реализовать

1. **Структура:**
   ```
   backend/            # Python 3.11+, пакет lyra/
     lyra/{api,core,db,ingest,retrieval,rag,evals,workers}/   # пустые пакеты с __init__.py и README-докстрингом о назначении
     pyproject.toml    # ruff, mypy(strict), pytest, зависимости: fastapi, uvicorn, pydantic v2, pydantic-settings, sqlalchemy[asyncio] 2.x, alembic, asyncpg, redis, celery, httpx, structlog, prometheus-client
     tests/
   frontend/           # React 18 + TypeScript + Vite, vitest, eslint+prettier
   infra/
     docker-compose.yml
     grafana/ prometheus/   # заготовки provisioning
   evals/              # пока пустая структура с README
   Makefile
   .github/workflows/ci.yml
   .env.example
   ```
2. **FastAPI-приложение** (`lyra/api/app.py`): фабрика приложения; конфиг через pydantic-settings (все настройки из env, префикс `LYRA_`); структурные логи structlog (JSON, request_id middleware); эндпоинты `GET /health` (liveness) и `GET /health/ready` (проверяет PostgreSQL, Redis, Ollama, TEI-embeddings, TEI-reranker — по каждому up/down, как в `docs/api-contract.md` §7); `GET /metrics` (prometheus-client).
3. **Celery-приложение** (`lyra/workers/celery_app.py`): брокер Redis, очереди `ingest`, `sync`, `evals`, `acks_late=True`; одна demo-задача ping для проверки.
4. **docker-compose** (`infra/docker-compose.yml`): сервисы `api`, `worker`, `frontend`, `postgres` (image с pgvector, например `pgvector/pgvector:pg16`), `redis`, `ollama` (+ команда предзагрузки модели `qwen2.5:7b-instruct-q4_K_M` — отдельный init-контейнер или make-цель), `embeddings` (ghcr.io/huggingface/text-embeddings-inference, модель BAAI/bge-m3), `reranker` (TEI, модель BAAI/bge-reranker-v2-m3). Healthchecks у всех; volumes для данных и моделей; `.env` подхватывается.
5. **Frontend:** Vite-болванка с одной страницей «LYRA», прокси `/api` на backend, eslint+prettier+vitest настроены, один smoke-тест рендера. Размещение тестов — рядом с кодом (`Component.test.tsx`), зафиксируй include-паттерном в конфиге vitest (правило `.claude/rules/typescript.md`).
6. **Makefile:** `make up`, `make down`, `make logs`, `make test` (pytest+vitest), `make lint`, `make pull-models`.
7. **CI (GitHub Actions):** jobs: lint (ruff, mypy, eslint), test-backend (pytest), test-frontend (vitest). Без docker-билдов тяжёлых моделей в CI.
8. **Гигиена:** `.gitignore` (включая `.env`), `.env.example` со ВСЕМИ переменными и плейсхолдерами (секретов в репозитории нет — правило из `docs/security-and-access.md` §5), pre-commit (ruff, prettier), контейнеры приложений от non-root пользователя.

## Критерии приёмки
- `docker compose -f infra/docker-compose.yml up` поднимает весь стек; `/health/ready` отдаёт статусы всех 5 зависимостей.
- `make test` и `make lint` зелёные локально; CI-workflow валиден и зелёный.
- README.md в корне: краткое описание, требования к железу (из `docs/nfr.md` §5), запуск за 3 команды.

## Тесты
- pytest: /health возвращает 200; /health/ready корректно репортит down при недоступной зависимости (мок); конфиг читается из env.
- vitest: smoke-тест страницы.

## Чего НЕ делать
Ни моделей БД, ни миграций, ни бизнес-логики — это фазы 1+. Не добавляй лишних зависимостей «на будущее».
