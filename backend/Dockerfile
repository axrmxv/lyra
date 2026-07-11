FROM python:3.11-slim

RUN useradd --create-home app
WORKDIR /app

COPY pyproject.toml alembic.ini ./
COPY migrations ./migrations
COPY lyra ./lyra
# dev-зависимости в MVP-образе сознательно: make test/lint выполняются в этом
# же контейнере; отдельный slim-образ для production — задача трека P3
RUN pip install --no-cache-dir ".[dev]"

COPY tests ./tests

USER app
EXPOSE 8000

# Миграции при старте: alembic upgrade head — контракт фазы 1
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn lyra.api.app:app --host 0.0.0.0 --port 8000"]
