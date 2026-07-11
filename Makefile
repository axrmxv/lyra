# LYRA — команды разработки. Windows: запускать из Git Bash или WSL (нужен make).
# Все test/lint выполняются в контейнерах — локальные python/node не обязательны.

COMPOSE := docker compose -f infra/docker-compose.yml --project-directory .

.PHONY: up down logs test test-backend test-frontend lint lint-backend lint-frontend pull-models

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

test: test-backend test-frontend

test-backend:
	$(COMPOSE) up -d postgres
	$(COMPOSE) exec -T postgres sh -c 'createdb -U $${POSTGRES_USER:-lyra} lyra_test 2>/dev/null || true'
	$(COMPOSE) run --rm api pytest

test-frontend:
	$(COMPOSE) run --rm --no-deps frontend sh -c "npm install && npm test"

lint: lint-backend lint-frontend

lint-backend:
	$(COMPOSE) run --rm --no-deps api sh -c "ruff check . && ruff format --check . && mypy lyra"

lint-frontend:
	$(COMPOSE) run --rm --no-deps frontend sh -c "npm install && npm run lint && npm run format"

# Модели Ollama тянутся в named volume ollama_models; модели TEI (bge-m3, reranker)
# скачиваются в hf_cache автоматически при первом старте контейнеров.
pull-models:
	$(COMPOSE) up -d ollama
	$(COMPOSE) exec ollama ollama pull qwen2.5:7b-instruct-q4_K_M
