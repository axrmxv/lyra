"""Схемы chat-API и SSE-событий (docs/api-contract.md §4)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from lyra.rag.state import AnswerPayload


class SessionCreateResponse(BaseModel):
    session_id: uuid.UUID


class SessionOut(BaseModel):
    id: uuid.UUID
    title: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionListResponse(BaseModel):
    items: list[SessionOut]
    total: int


class CitationOut(BaseModel):
    id: int
    chunk_id: uuid.UUID | None
    document_id: uuid.UUID | None
    document_title: str
    url: str | None
    quote: str
    relevance_score: float


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    confidence: dict[str, float | str] | None
    refusal: bool = False
    created_at: datetime
    citations: list[CitationOut] = Field(default_factory=list)


class MessageListResponse(BaseModel):
    items: list[MessageOut]
    total: int


class ChatMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    collection_id: uuid.UUID | None = None


class UsageOut(BaseModel):
    llm_calls: int
    prompt_tokens: int
    completion_tokens: int
    took_ms: int


class DocumentRefOut(BaseModel):
    document_id: uuid.UUID
    title: str
    url: str | None


class ConfidenceOut(BaseModel):
    label: str
    score: float


class FinalEvent(BaseModel):
    """data события `final` — полный payload ответа."""

    message_id: uuid.UUID
    answer: str
    refusal: bool
    citations: list[CitationOut]
    confidence: ConfidenceOut
    degraded: bool
    trace_id: str
    usage: UsageOut
    nearest_documents: list[DocumentRefOut] = Field(default_factory=list)

    @classmethod
    def from_payload(
        cls, payload: AnswerPayload, *, message_id: uuid.UUID, trace_id: str
    ) -> "FinalEvent":
        return cls(
            message_id=message_id,
            answer=payload.answer,
            refusal=payload.refusal,
            citations=[
                CitationOut(
                    id=item.id,
                    chunk_id=item.chunk_id,
                    document_id=item.document_id,
                    document_title=item.document_title,
                    url=item.url,
                    quote=item.quote,
                    relevance_score=item.relevance_score,
                )
                for item in payload.citations
            ],
            confidence=ConfidenceOut(
                label=payload.confidence.label, score=payload.confidence.score
            ),
            degraded=payload.degraded,
            trace_id=trace_id,
            usage=UsageOut(
                llm_calls=payload.usage.llm_calls,
                prompt_tokens=payload.usage.prompt_tokens,
                completion_tokens=payload.usage.completion_tokens,
                took_ms=payload.usage.took_ms,
            ),
            nearest_documents=[
                DocumentRefOut(document_id=ref.document_id, title=ref.title, url=ref.url)
                for ref in payload.nearest_documents
            ],
        )
