"""Чат: сессии, сообщения, цитаты, фидбек (docs/data-model.md §2)."""

import uuid
from typing import Any

from sqlalchemy import Enum, Float, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from lyra.db.base import Base, IdTimestampMixin, TenantMixin
from lyra.db.models.enums import FeedbackRating, MessageRole


class ChatSession(IdTimestampMixin, TenantMixin, Base):
    __tablename__ = "chat_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str | None] = mapped_column(Text)


class Message(IdTimestampMixin, TenantMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_session_created", "session_id", "created_at"),)

    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_sessions.id"))
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, name="message_role", values_callable=lambda e: [m.value for m in e])
    )
    content: Mapped[str] = mapped_column(Text)
    confidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    trace_id: Mapped[str | None] = mapped_column(Text)
    # Вердикты sufficiency/self_check, итерации corrective, degraded — аудит и отладка
    graph_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class MessageCitation(IdTimestampMixin, TenantMixin, Base):
    __tablename__ = "message_citations"

    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id"))
    # SET NULL: GC-чистка chunks не рвёт историю — quote-текст сохраняется здесь
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chunks.id", ondelete="SET NULL"))
    marker: Mapped[int]
    quote: Mapped[str] = mapped_column(Text)
    relevance_score: Mapped[float] = mapped_column(Float)


class Feedback(IdTimestampMixin, TenantMixin, Base):
    __tablename__ = "feedback"

    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    rating: Mapped[FeedbackRating] = mapped_column(
        Enum(
            FeedbackRating,
            name="feedback_rating",
            values_callable=lambda e: [m.value for m in e],
        )
    )
    comment: Mapped[str | None] = mapped_column(Text)
