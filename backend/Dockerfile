FROM python:3.11-slim

RUN useradd --create-home app
WORKDIR /app

COPY pyproject.toml ./
COPY lyra ./lyra
# dev-зависимости в MVP-образе сознательно: make test/lint выполняются в этом
# же контейнере; отдельный slim-образ для production — задача трека P3
RUN pip install --no-cache-dir ".[dev]"

COPY tests ./tests

USER app
EXPOSE 8000

CMD ["uvicorn", "lyra.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
