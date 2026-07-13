"""Схемы POST /search (docs/api-contract.md §3)."""

import uuid
from typing import Any

from pydantic import BaseModel, Field

from lyra.retrieval.interfaces import ScoredChunk


class SearchFiltersIn(BaseModel):
    source_type: list[str] = Field(default_factory=list)
    lang: str | None = None
    source_id: uuid.UUID | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    collection_id: uuid.UUID | None = None
    top_k: int = Field(default=10, ge=1, le=50)
    filters: SearchFiltersIn = Field(default_factory=SearchFiltersIn)
    rerank: bool = True


class ScoresOut(BaseModel):
    bm25_rank: int | None
    vector_rank: int | None
    rrf: float
    rerank: float | None


class DocumentRef(BaseModel):
    id: uuid.UUID
    title: str
    url: str | None
    headings_path: list[str]
    source_updated_at: str | None


class SearchResultItem(BaseModel):
    chunk_id: uuid.UUID
    text: str
    score: float
    scores: ScoresOut
    document: DocumentRef

    @classmethod
    def from_chunk(cls, chunk: ScoredChunk) -> "SearchResultItem":
        meta: dict[str, Any] = chunk.meta
        return cls(
            chunk_id=chunk.chunk_id,
            text=chunk.text,
            score=chunk.final_score,
            scores=ScoresOut(
                bm25_rank=chunk.bm25_rank,
                vector_rank=chunk.vector_rank,
                rrf=chunk.rrf_score,
                rerank=chunk.rerank_score,
            ),
            document=DocumentRef(
                id=chunk.document_id,
                title=str(meta.get("doc_title", "")),
                url=meta.get("url"),
                headings_path=list(meta.get("headings_path", [])),
                source_updated_at=meta.get("source_updated_at"),
            ),
        )


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    degraded: bool
    took_ms: int
