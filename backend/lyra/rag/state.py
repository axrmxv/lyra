"""Контракт state RAG-графа — строго по таблице ADR-006.

Узлы обмениваются данными ТОЛЬКО через state; изменение полей = ревизия ADR.
"""

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from lyra.retrieval.interfaces import ScoredChunk


class Sufficiency(BaseModel):
    sufficient: bool
    score: float = Field(ge=0.0, le=1.0)
    missing_aspects: list[str] = Field(default_factory=list)


class SelfCheckResult(BaseModel):
    passed: bool
    unsupported_claims: list[str] = Field(default_factory=list)


class CitationItem(BaseModel):
    id: int  # маркер [n]
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    url: str | None
    quote: str
    relevance_score: float


class Confidence(BaseModel):
    label: str  # high | medium | low
    score: float


class DocumentRef(BaseModel):
    document_id: uuid.UUID
    title: str
    url: str | None


class Usage(BaseModel):
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    took_ms: int = 0


class AnswerPayload(BaseModel):
    answer: str
    refusal: bool
    citations: list[CitationItem]
    confidence: Confidence
    degraded: bool
    nearest_documents: list[DocumentRef] = Field(default_factory=list)
    usage: Usage


class RagState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Вход
    question: str
    chat_history: list[dict[str, str]] = Field(default_factory=list)
    collection_id: uuid.UUID | None = None
    tenant_id: uuid.UUID

    # Промежуточные (по таблице ADR-006)
    condensed_question: str | None = None
    retrieved_chunks: list[ScoredChunk] = Field(default_factory=list)
    sufficiency: Sufficiency | None = None
    corrective_iterations: int = 0
    draft_answer: str | None = None
    citations: list[CitationItem] = Field(default_factory=list)
    cite_error: str | None = None
    self_check: SelfCheckResult | None = None
    generate_retries: int = 0
    degraded: bool = False

    # Контекст генерации: нумерованные источники [1..k] (фиксируется в generate,
    # используется cite/self_check — маркеры маппятся на эти chunks)
    context_chunks: list[ScoredChunk] = Field(default_factory=list)

    # Учёт (FR-19): счётчики наполняются обвязкой графа из метрик LLMClient
    usage: Usage = Field(default_factory=Usage)

    # Выход
    final: AnswerPayload | None = None

    def bump_usage(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.usage.llm_calls += 1
        self.usage.prompt_tokens += prompt_tokens
        self.usage.completion_tokens += completion_tokens

    def meta_snapshot(self) -> dict[str, Any]:
        """graph_meta для аудита (messages.graph_meta, data-model)."""
        return {
            "condensed_question": self.condensed_question,
            "sufficiency": self.sufficiency.model_dump() if self.sufficiency else None,
            "corrective_iterations": self.corrective_iterations,
            "generate_retries": self.generate_retries,
            "self_check": self.self_check.model_dump() if self.self_check else None,
            "degraded": self.degraded,
            "cite_error": self.cite_error,
        }
