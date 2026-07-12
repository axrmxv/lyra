"""Каналы поиска: PgVectorStore (ANN, HNSW) и BM25 (tsvector).

Оба канала:
- видят только chunks активных версий активных документов (data-model §3);
- применяют фильтры метаданных ДО ранжирования;
- принимают access_context (задел ACL — в MVP не фильтрует).
"""

import uuid
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lyra.db.models import Chunk, Document, DocumentStatus, DocumentVersion, VersionStatus
from lyra.retrieval.interfaces import AccessContext, ScoredChunk, SearchFilters


def _base_query(tenant_id: uuid.UUID, filters: SearchFilters) -> Select[Any]:
    query = (
        select(Chunk, DocumentVersion.document_id)
        .join(DocumentVersion, Chunk.document_version_id == DocumentVersion.id)
        .join(Document, DocumentVersion.document_id == Document.id)
        .where(
            Chunk.tenant_id == tenant_id,
            DocumentVersion.status == VersionStatus.ACTIVE,
            Document.status == DocumentStatus.ACTIVE,
        )
    )
    if filters.collection_id is not None:
        query = query.where(Chunk.collection_id == filters.collection_id)
    if filters.source_id is not None:
        query = query.where(Document.source_id == filters.source_id)
    if filters.source_type:
        query = query.where(Chunk.meta["source_type"].astext.in_(filters.source_type))
    if filters.lang is not None:
        query = query.where(Chunk.meta["lang"].astext == filters.lang)
    return query


def _to_scored(chunk: Chunk, document_id: uuid.UUID) -> ScoredChunk:
    embedding = chunk.embedding
    return ScoredChunk(
        chunk_id=chunk.id,
        document_id=document_id,
        document_version_id=chunk.document_version_id,
        ordinal=chunk.ordinal,
        text=chunk.text,
        token_count=chunk.token_count,
        meta=chunk.meta,
        embedding=list(embedding) if embedding is not None else None,
    )


class PgVectorStore:
    """Реализация VectorStore для MVP (ADR-001). Retrieval-код знает только интерфейс."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(
        self,
        query_vector: list[float],
        *,
        tenant_id: uuid.UUID,
        filters: SearchFilters,
        access_context: AccessContext,
        top_k: int,
    ) -> list[ScoredChunk]:
        del access_context  # задел ACL: фильтр врезается здесь (production P1)
        distance = Chunk.embedding.cosine_distance(query_vector)
        query = _base_query(tenant_id, filters).order_by(distance).limit(top_k)
        result = await self._session.execute(query)
        scored: list[ScoredChunk] = []
        for rank, (chunk, document_id) in enumerate(result.all(), start=1):
            item = _to_scored(chunk, document_id)
            item.vector_rank = rank
            scored.append(item)
        return scored


class Bm25Store:
    """Лексический канал: websearch_to_tsquery (russian) + ts_rank_cd (ADR-005)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(
        self,
        query: str,
        *,
        tenant_id: uuid.UUID,
        filters: SearchFilters,
        access_context: AccessContext,
        top_k: int,
    ) -> list[ScoredChunk]:
        del access_context  # задел ACL (см. PgVectorStore)
        tsquery = func.websearch_to_tsquery("russian", query)
        rank = func.ts_rank_cd(Chunk.tsv, tsquery)
        statement = (
            _base_query(tenant_id, filters)
            .where(Chunk.tsv.op("@@")(tsquery))
            .order_by(rank.desc())
            .limit(top_k)
        )
        result = await self._session.execute(statement)
        scored: list[ScoredChunk] = []
        for position, (chunk, document_id) in enumerate(result.all(), start=1):
            item = _to_scored(chunk, document_id)
            item.bm25_rank = position
            scored.append(item)
        return scored
