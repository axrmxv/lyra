"""Репозиторий чата: сессии и сообщения. Доступ — только к своим сессиям."""

import uuid
from typing import Any

from sqlalchemy import select

from lyra.db.models import ChatSession, Message, MessageRole
from lyra.db.repositories.base import BaseRepository


class ChatRepository(BaseRepository):
    async def create_session(
        self, tenant_id: uuid.UUID, *, user_id: uuid.UUID, title: str | None = None
    ) -> ChatSession:
        chat_session = ChatSession(tenant_id=tenant_id, user_id=user_id, title=title)
        self.session.add(chat_session)
        await self.session.flush()
        return chat_session

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
