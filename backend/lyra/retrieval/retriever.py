"""HybridRetriever — фасад retrieval-слоя (architecture.md §3).

Пайплайн: кэш → embedding запроса (кэш) → BM25 ∥ вектор → RRF → reranker
(graceful degradation) → дедуп → MMR → top_k. Единственная точка выдачи
данных корпуса — сюда врезается ACL-фильтр в production.
"""

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import TypeVar

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lyra.core.clients import EmbeddingClient
from lyra.core.clients.reranker import RerankerClient, RerankerUnavailable
from lyra.core.config import Settings
from lyra.core.metrics import RETRIEVAL_DEGRADED, RETRIEVAL_STEP_SECONDS
from lyra.retrieval import cache as cache_module
from lyra.retrieval.cache import RetrievalCache
from lyra.retrieval.channels import Bm25Store, PgVectorStore
from lyra.retrieval.fusion import RRFFuser
from lyra.retrieval.interfaces import (
    AccessContext,
    RetrievalResult,
    ScoredChunk,
    SearchFilters,
)
from lyra.retrieval.postprocess import dedup_exact, mmr_select

logger = structlog.get_logger(__name__)

T = TypeVar("T")

CHANNEL_TOP_K = 50  # top-N каждого канала до fusion (ADR-005)


async def _timed(step: str, coro: Awaitable[T]) -> T:
    started = time.monotonic()
    try:
        return await coro
    finally:
        RETRIEVAL_STEP_SECONDS.labels(step=step).observe(time.monotonic() - started)


def _timed_sync(step: str, fn: Callable[[], T]) -> T:
    started = time.monotonic()
    try:
        return fn()
    finally:
        RETRIEVAL_STEP_SECONDS.labels(step=step).observe(time.monotonic() - started)


class HybridRetriever:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        *,
        embedding_client: EmbeddingClient | None = None,
        reranker_client: RerankerClient | None = None,
        retrieval_cache: RetrievalCache | None = None,
    ) -> None:
        # Каналы выполняются параллельно (ADR-005) — каждому нужна СВОЯ сессия:
        # одно asyncpg-соединение не выдерживает конкурентных запросов
        self._session_factory = session_factory
        self._fuser = RRFFuser()
        self._embeddings = embedding_client or EmbeddingClient(settings.embeddings_url)
        self._reranker = reranker_client or RerankerClient(
            settings.reranker_url,
            timeout_s=settings.reranker_timeout_s,
            text_max_chars=settings.rerank_text_max_chars,
        )
        self._rerank_top_n = settings.rerank_top_n
        self._cache = retrieval_cache or RetrievalCache(settings.redis_url)

    async def retrieve(
        self,
        query: str,
        *,
        tenant_id: uuid.UUID,
        filters: SearchFilters | None = None,
        access_context: AccessContext | None = None,
        top_k: int = 8,
        rerank: bool = True,
    ) -> RetrievalResult:
        started = time.monotonic()
        filters = filters or SearchFilters()
        access_context = access_context or AccessContext()

        result_key = cache_module.result_key(query, tenant_id, filters, top_k, rerank)
        cached = await self._cache.get_result(result_key)
        if cached is not None:
            return RetrievalResult(
                chunks=cached,
                from_cache=True,
                took_ms=int((time.monotonic() - started) * 1000),
            )

        query_vector = await self._query_embedding(query)

        async def bm25_search() -> list[ScoredChunk]:
            async with self._session_factory() as session:
                return await Bm25Store(session).search(
                    query,
                    tenant_id=tenant_id,
                    filters=filters,
                    access_context=access_context,
                    top_k=CHANNEL_TOP_K,
                )

        async def vector_search() -> list[ScoredChunk]:
            async with self._session_factory() as session:
                return await PgVectorStore(session).search(
                    query_vector,
                    tenant_id=tenant_id,
                    filters=filters,
                    access_context=access_context,
                    top_k=CHANNEL_TOP_K,
                )

        bm25_chunks, vector_chunks = await asyncio.gather(
            _timed("bm25", bm25_search()), _timed("vector", vector_search())
        )
        fused = _timed_sync("fuse", lambda: self._fuser.fuse([bm25_chunks, vector_chunks]))

        degraded = False
        candidates = fused
        if rerank and fused:
            # На rerank идёт только голова RRF-списка (CPU-бюджет, конфиг);
            # хвост сохраняет RRF-порядок ниже переранжированной головы
            head, tail = fused[: self._rerank_top_n], fused[self._rerank_top_n :]
            try:
                reranked = await _timed("rerank", self._reranker.rerank(query, head))
                candidates = reranked + tail
            except RerankerUnavailable as exc:
                # Graceful degradation (ADR-004): RRF-порядок, флаг в ответ и метрику
                degraded = True
                RETRIEVAL_DEGRADED.inc()
                logger.warning("reranker_degraded", error=str(exc) or type(exc).__name__)

        def postprocess() -> list[ScoredChunk]:
            deduped = dedup_exact(candidates)
            return mmr_select(deduped, top_k=top_k)

        final = _timed_sync("postprocess", postprocess)
        if not degraded:
            await self._cache.set_result(result_key, final)
        return RetrievalResult(
            chunks=final,
            degraded=degraded,
            took_ms=int((time.monotonic() - started) * 1000),
        )

    async def _query_embedding(self, query: str) -> list[float]:
        cached = await self._cache.get_embedding(query)
        if cached is not None:
            return cached
        vector = await _timed("embed_query", self._embeddings.embed_one(query))
        await self._cache.set_embedding(query, vector)
        return vector
