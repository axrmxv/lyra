# LYRA — Гармония знаний

[![CI](https://github.com/axrmxv/lyra/actions/workflows/ci.yml/badge.svg)](https://github.com/axrmxv/lyra/actions/workflows/ci.yml)

RAG-платформа корпоративных знаний: гибридный поиск (BM25 + вектор + RRF + reranker),
LangGraph-граф с проверкой достаточности контекста и **обязательными цитатами источников**.
Вопрос вне базы знаний получает честный отказ, а не галлюцинацию.

Полностью self-hosted: Ollama (Qwen2.5-7B), bge-m3, bge-reranker-v2-m3 — без внешних API-ключей.

## Стек

FastAPI · Pydantic v2 · SQLAlchemy 2.0 async · LangGraph · Celery + Redis ·
PostgreSQL + pgvector · React 18 + TypeScript + Vite · Docker Compose · Prometheus/Grafana

## Требования (docs/nfr.md §5)

- Docker Desktop (Windows — WSL2-бэкенд с ≥ 12 ГБ RAM)
- Минимум: 4 CPU / 16 ГБ RAM / 20 ГБ диска (модели ~10 ГБ)
- GPU опционален (ускоряет ответы с ~8 с до ~2–3 с)

## Быстрый старт

```bash
cp .env.example .env        # заполнить секреты
make up                     # собрать и поднять весь стек
make pull-models            # скачать LLM (~4.7 ГБ; модели TEI скачаются сами)
```

Проверка: `curl http://localhost:8000/health/ready` — все 5 зависимостей `up`.
UI: http://localhost:5173 · API: http://localhost:8000/docs

На Windows `make` доступен из Git Bash/WSL; без make — команды видны в `Makefile`
(compose вызывается как `docker compose -f infra/docker-compose.yml --project-directory .`).

## Команды

| Команда | Действие |
|---|---|
| `make up` / `make down` / `make logs` | Стек: старт / стоп / логи |
| `make test` | pytest + vitest (в контейнерах) |
| `make lint` | ruff + mypy + eslint + prettier |
| `make pull-models` | Загрузка LLM в volume `ollama_models` |

Хуки: `pre-commit install && pre-commit install --hook-type commit-msg` (обязательно).

## Документация

- Продукт: [docs/PRD.md](docs/PRD.md) · Архитектура: [docs/architecture.md](docs/architecture.md)
- Решения: [docs/adr/](docs/adr/) — 10 ADR · Роадмап: [PLAN.md](PLAN.md)
- Качество: [docs/eval-plan.md](docs/eval-plan.md) · Безопасность: [docs/security-and-access.md](docs/security-and-access.md)

## Статус

Фаза 0 (скаффолдинг) — см. [PLAN.md](PLAN.md): фазы 0–7 = MVP, P1–P4 = production-трек.

## Наблюдаемость (фаза 6)

- Prometheus: http://localhost:9090, Grafana: http://localhost:3000
  (дашборд «LYRA — обзор» провижинится автоматически).
- LLM-трейсы — структурные логи внутри контура (наружу не отправляются,
  docs/security-and-access.md §5). Просмотр трейса запроса по trace_id:

```bash
docker logs lyra-api-1 2>&1 | grep '"llm_call"' \
  | jq -r 'select(.trace_id=="tr_...") | [.node,.model,.prompt_tokens,.completion_tokens,.duration_ms] | @tsv'
```
