"""Клиент TEI-reranker (bge-reranker-v2-m3, ADR-004).

Graceful degradation — обязанность вызывающего (Retriever): таймаут/ошибка
пробрасывается как RerankerUnavailable, retrieval продолжает c RRF-порядком.
"""

import httpx
import structlog

from lyra.retrieval.interfaces import ScoredChunk

logger = structlog.get_logger(__name__)

RERANK_TIMEOUT_S = 15.0  # CPU-стенд; ADR-004: на GPU вернуть 3с
TEXT_MAX_CHARS = 600  # скорим начало chunk (префикс+начало) — CPU-компромисс


class RerankerUnavailable(Exception):
    pass


class RerankerClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = RERANK_TIMEOUT_S,
        text_max_chars: int = TEXT_MAX_CHARS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._text_max_chars = text_max_chars

    async def rerank(self, query: str, chunks: list[ScoredChunk]) -> list[ScoredChunk]:
        """Проставляет rerank_score и сортирует по нему (по убыванию)."""
        if not chunks:
            return chunks
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                response = await client.post(
                    f"{self._base_url}/rerank",
                    json={
                        "query": query,
                        "texts": [chunk.text[: self._text_max_chars] for chunk in chunks],
                        "truncate": True,
                    },
                )
                response.raise_for_status()
                payload: list[dict[str, float]] = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # str(ReadTimeout) пуст — имя типа обязательно для диагностики
            raise RerankerUnavailable(f"{type(exc).__name__}: {exc}") from exc

        for entry in payload:
            chunks[int(entry["index"])].rerank_score = float(entry["score"])
        return sorted(
            chunks,
            key=lambda c: (
                -(c.rerank_score if c.rerank_score is not None else -1.0),
                str(c.chunk_id),
            ),
        )
