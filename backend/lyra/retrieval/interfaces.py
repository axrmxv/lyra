"""Контракты retrieval-слоя (ADR-001, ADR-005).

Весь векторный доступ — только через VectorStore (точка миграции на Qdrant);
любой путь выдачи данных проходит через Retriever — сюда в production
врезается ACL-фильтр (access_context, docs/security-and-access.md §3).
"""

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class AccessContext:
    """Задел doc-level ACL: в MVP всегда «разрешено всё» (enforcement выключен).

    Поле обязано прокидываться через все каналы ДО ранжирования —
    пост-фильтрация после rerank запрещена (.claude/rules/retrieval.md).
    """

    allow_all: bool = True


@dataclass(frozen=True)
class SearchFilters:
    collection_id: uuid.UUID | None = None
    source_id: uuid.UUID | None = None
    source_type: tuple[str, ...] = ()
    lang: str | None = None

    def cache_key_part(self) -> str:
        return (
            f"{self.collection_id}|{self.source_id}|{','.join(sorted(self.source_type))}"
            f"|{self.lang}"
        )


@dataclass
class ScoredChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    ordinal: int
    text: str
    token_count: int
    meta: dict[str, Any]
    embedding: list[float] | None = None  # нужен MMR; в кэш/ответ не сериализуется
    # Скоры по каналам (None — не попал в канал)
    bm25_rank: int | None = None
    vector_rank: int | None = None
    rrf_score: float = 0.0
    rerank_score: float | None = None

    @property
    def final_score(self) -> float:
        return self.rerank_score if self.rerank_score is not None else self.rrf_score


@dataclass
class RetrievalResult:
    chunks: list[ScoredChunk]
    degraded: bool = False  # reranker/кэш недоступны — качество может быть ниже
    took_ms: int = 0
    from_cache: bool = False


class VectorStore(Protocol):
    """ANN-поиск. Реализация MVP — PgVectorStore; production — QdrantVectorStore."""

    async def search(
        self,
        query_vector: list[float],
        *,
        tenant_id: uuid.UUID,
        filters: SearchFilters,
        access_context: AccessContext,
        top_k: int,
    ) -> list[ScoredChunk]: ...


class LexicalStore(Protocol):
    """BM25-класс канал (tsvector в MVP)."""

    async def search(
        self,
        query: str,
        *,
        tenant_id: uuid.UUID,
        filters: SearchFilters,
        access_context: AccessContext,
        top_k: int,
    ) -> list[ScoredChunk]: ...


class Fuser(Protocol):
    """Слияние ранжированных списков каналов (ADR-005). Смена стратегии — конфигом."""

    def fuse(self, channels: list[list[ScoredChunk]]) -> list[ScoredChunk]: ...


class Reranker(Protocol):
    async def rerank(self, query: str, chunks: list[ScoredChunk]) -> list[ScoredChunk]: ...


@dataclass
class RerankOutcome:
    chunks: list[ScoredChunk]
    degraded: bool = field(default=False)
