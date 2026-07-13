"""Redis-кэш retrieval (docs/context-management.md §7). Fail-open:
недоступный Redis замедляет запросы, но не ломает поиск.

Ключи при появлении ACL/tenant обязаны включать их (.claude/rules/retrieval.md);
tenant_id входит в ключ уже сейчас.
"""

import hashlib
import json
import uuid
from typing import Any

import structlog
from redis.asyncio import Redis

from lyra.core.metrics import CACHE_HITS, CACHE_MISSES
from lyra.retrieval.interfaces import ScoredChunk, SearchFilters

logger = structlog.get_logger(__name__)

EMBEDDING_TTL_S = 24 * 3600
RESULT_TTL_S = 15 * 60


def _normalize_query(query: str) -> str:
    return " ".join(query.lower().split())


def embedding_key(query: str) -> str:
    digest = hashlib.sha256(_normalize_query(query).encode()).hexdigest()
    return f"emb:{digest}"


def result_key(
    query: str, tenant_id: uuid.UUID, filters: SearchFilters, top_k: int, rerank: bool
) -> str:
    raw = f"{_normalize_query(query)}|{tenant_id}|{filters.cache_key_part()}|{top_k}|{rerank}"
    return f"ret:{hashlib.sha256(raw.encode()).hexdigest()}"


def _chunk_to_json(chunk: ScoredChunk) -> dict[str, Any]:
    payload = {
        "chunk_id": str(chunk.chunk_id),
        "document_id": str(chunk.document_id),
        "document_version_id": str(chunk.document_version_id),
        "ordinal": chunk.ordinal,
        "text": chunk.text,
        "token_count": chunk.token_count,
        "meta": chunk.meta,
        "bm25_rank": chunk.bm25_rank,
        "vector_rank": chunk.vector_rank,
        "rrf_score": chunk.rrf_score,
        "rerank_score": chunk.rerank_score,
    }
    return payload


def _chunk_from_json(payload: dict[str, Any]) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=uuid.UUID(payload["chunk_id"]),
        document_id=uuid.UUID(payload["document_id"]),
        document_version_id=uuid.UUID(payload["document_version_id"]),
        ordinal=payload["ordinal"],
        text=payload["text"],
        token_count=payload["token_count"],
        meta=payload["meta"],
        embedding=None,  # эмбеддинги в кэш не пишутся (объём)
        bm25_rank=payload["bm25_rank"],
        vector_rank=payload["vector_rank"],
        rrf_score=payload["rrf_score"],
        rerank_score=payload["rerank_score"],
    )


class RetrievalCache:
    def __init__(self, redis_url: str) -> None:
        self._client: Redis = Redis.from_url(redis_url, socket_timeout=1.0)

    async def _get(self, key: str, cache_name: str) -> str | None:
        try:
            value = await self._client.get(key)
        except Exception as exc:
            logger.warning("cache_unavailable", op="get", error=str(exc))
            return None
        if value is None:
            CACHE_MISSES.labels(cache=cache_name).inc()
            return None
        CACHE_HITS.labels(cache=cache_name).inc()
        return value.decode() if isinstance(value, bytes) else str(value)

    async def _set(self, key: str, value: str, ttl_s: int) -> None:
        try:
            await self._client.set(key, value, ex=ttl_s)
        except Exception as exc:
            logger.warning("cache_unavailable", op="set", error=str(exc))

    async def get_embedding(self, query: str) -> list[float] | None:
        raw = await self._get(embedding_key(query), "embedding")
        return json.loads(raw) if raw else None

    async def set_embedding(self, query: str, vector: list[float]) -> None:
        await self._set(embedding_key(query), json.dumps(vector), EMBEDDING_TTL_S)

    async def get_result(self, key: str) -> list[ScoredChunk] | None:
        raw = await self._get(key, "retrieval")
        if raw is None:
            return None
        return [_chunk_from_json(item) for item in json.loads(raw)]

    async def set_result(self, key: str, chunks: list[ScoredChunk]) -> None:
        payload = json.dumps([_chunk_to_json(chunk) for chunk in chunks], ensure_ascii=False)
        await self._set(key, payload, RESULT_TTL_S)
