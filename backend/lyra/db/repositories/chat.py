"""Репозиторий чата: сессии, сообщения, цитаты. Доступ — только к своим сессиям."""

import uuid
from typing import Any

from sqlalchemy import func, select

from lyra.db.models import (
    ChatSession,
    Chunk,
    DocumentVersion,
    Message,
    MessageCitation,
    MessageRole,
)
from lyra.db.repositories.base import BaseRepository


class ChatRepository(BaseRepository):
    async def create_session(
        self, tenant_id: uuid.UUID, *, user_id: uuid.UUID, title: str | None = None
    ) -> ChatSession:
        chat_session = ChatSession(tenant_id=tenant_id, user_id=user_id, title=title)
        self.session.add(chat_session)
        await self.session.flush()
        return chat_session

    async def get_session(self, tenant_id: uuid.UUID, session_id: uuid.UUID) -> ChatSession | None:
        """Без фильтра владельца: 404/403 различает сервисный слой."""
        result = await self.session.execute(
            select(ChatSession).where(
                ChatSession.tenant_id == tenant_id, ChatSession.id == session_id
            )
        )
        return result.scalar_one_or_none()

    async def get_session_for_user(
        self, tenant_id: uuid.UUID, session_id: uuid.UUID, user_id: uuid.UUID
    ) -> ChatSession | None:
        """None и для чужой сессии — проверка владения на уровне запроса."""
        result = await self.session.execute(
            select(ChatSession).where(
                ChatSession.tenant_id == tenant_id,
                ChatSession.id == session_id,
                ChatSession.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_sessions(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> list[ChatSession]:
        result = await self.session.execute(
            select(ChatSession)
            .where(ChatSession.tenant_id == tenant_id, ChatSession.user_id == user_id)
            .order_by(ChatSession.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars())

    async def count_sessions(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(ChatSession)
            .where(ChatSession.tenant_id == tenant_id, ChatSession.user_id == user_id)
        )
        return int(result.scalar_one())

    async def set_session_title(
        self, tenant_id: uuid.UUID, session_id: uuid.UUID, title: str
    ) -> None:
        chat_session = await self.get_session(tenant_id, session_id)
        if chat_session is not None and chat_session.title is None:
            chat_session.title = title
            await self.session.flush()

    async def add_message(
        self,
        tenant_id: uuid.UUID,
        *,
        session_id: uuid.UUID,
        role: MessageRole,
        content: str,
        confidence: dict[str, Any] | None = None,
        trace_id: str | None = None,
        graph_meta: dict[str, Any] | None = None,
    ) -> Message:
        message = Message(
            tenant_id=tenant_id,
            session_id=session_id,
            role=role,
            content=content,
            confidence=confidence,
            trace_id=trace_id,
            graph_meta=graph_meta,
        )
        self.session.add(message)
        await self.session.flush()
        return message

    async def list_messages(
        self, tenant_id: uuid.UUID, session_id: uuid.UUID, *, limit: int = 200, offset: int = 0
    ) -> list[Message]:
        result = await self.session.execute(
            select(Message)
            .where(Message.tenant_id == tenant_id, Message.session_id == session_id)
            .order_by(Message.created_at)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars())

    async def count_messages(self, tenant_id: uuid.UUID, session_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(Message)
            .where(Message.tenant_id == tenant_id, Message.session_id == session_id)
        )
        return int(result.scalar_one())

    async def get_message_with_owner(
        self, tenant_id: uuid.UUID, message_id: uuid.UUID
    ) -> tuple[Message, uuid.UUID] | None:
        """(сообщение, user_id владельца сессии) — проверка прав feedback."""
        result = await self.session.execute(
            select(Message, ChatSession.user_id)
            .join(ChatSession, Message.session_id == ChatSession.id)
            .where(Message.tenant_id == tenant_id, Message.id == message_id)
        )
        row = result.one_or_none()
        return (row[0], row[1]) if row is not None else None

    async def add_citations(
        self,
        tenant_id: uuid.UUID,
        *,
        message_id: uuid.UUID,
        citations: list[dict[str, Any]],
    ) -> None:
        """citations: [{chunk_id, marker, quote, relevance_score}]."""
        for item in citations:
            self.session.add(
                MessageCitation(
                    tenant_id=tenant_id,
                    message_id=message_id,
                    chunk_id=item["chunk_id"],
                    marker=item["marker"],
                    quote=item["quote"],
                    relevance_score=item["relevance_score"],
                )
            )
        await self.session.flush()

    async def list_citations_for_messages(
        self, tenant_id: uuid.UUID, message_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[dict[str, Any]]]:
        """Цитаты истории по message_id; title/url — из chunk.metadata,
        document_id — через document_versions. Chunk мог быть удалён GC
        (chunk_id SET NULL) — тогда quote остаётся, метаданные пустые."""
        if not message_ids:
            return {}
        result = await self.session.execute(
            select(MessageCitation, Chunk.meta, DocumentVersion.document_id)
            .outerjoin(Chunk, MessageCitation.chunk_id == Chunk.id)
            .outerjoin(DocumentVersion, Chunk.document_version_id == DocumentVersion.id)
            .where(
                MessageCitation.tenant_id == tenant_id,
                MessageCitation.message_id.in_(message_ids),
            )
            .order_by(MessageCitation.marker)
        )
        grouped: dict[uuid.UUID, list[dict[str, Any]]] = {}
        for citation, chunk_meta, document_id in result.all():
            meta = chunk_meta or {}
            grouped.setdefault(citation.message_id, []).append(
                {
                    "id": citation.marker,
                    "chunk_id": citation.chunk_id,
                    "document_id": document_id,
                    "document_title": str(meta.get("doc_title", "")),
                    "url": meta.get("url"),
                    "quote": citation.quote,
                    "relevance_score": citation.relevance_score,
                }
            )
        return grouped
