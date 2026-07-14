"""Клиент TEI-эмбеддингов (bge-m3, ADR-003): батчи, retry c backoff.

Используется ingest-пайплайном (векторизация chunks) и retrieval-слоем
фазы 3 (векторизация запросов) — один путь для обоих.
"""

import asyncio

import httpx
import structlog

logger = structlog.get_logger(__name__)

# Окно ретраев перекрывает рестарт TEI после OOM-kill (~90-120с c загрузкой
# модели; restart: unless-stopped в compose): 1+2+4+8+16+30+30+30 ≈ 121с
MAX_RETRIES = 8
BACKOFF_BASE_S = 1.0
BACKOFF_CAP_S = 30.0


class EmbeddingError(Exception):
    """Сервис недоступен после всех retry (transient — задача ретраится)."""


class EmbeddingClient:
    def __init__(self, base_url: str, *, batch_size: int = 16, timeout_s: float = 60.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._batch_size = batch_size
        self._timeout_s = timeout_s

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Векторизация списка текстов; порядок результата = порядку входа."""
        vectors: list[list[float]] = []
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            for start in range(0, len(texts), self._batch_size):
                batch = texts[start : start + self._batch_size]
                vectors.extend(await self._embed_batch(client, batch))
        return vectors

    async def embed_one(self, text: str) -> list[float]:
        result = await self.embed([text])
        return result[0]

    async def _embed_batch(self, client: httpx.AsyncClient, batch: list[str]) -> list[list[float]]:
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                response = await client.post(
                    f"{self._base_url}/embed", json={"inputs": batch, "truncate": True}
                )
                response.raise_for_status()
                data: list[list[float]] = response.json()
                return data
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                delay = min(BACKOFF_BASE_S * 2**attempt, BACKOFF_CAP_S)
                logger.warning(
                    "embedding_retry", attempt=attempt + 1, delay_s=delay, error=str(exc)
                )
                await asyncio.sleep(delay)
        raise EmbeddingError(f"TEI недоступен после {MAX_RETRIES} попыток: {last_error}")
