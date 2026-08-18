"""Репозиторий сессий входа (ADR-012).

Сессия — единица отзыва: access-токен несёт её id в jti, поэтому проверка
живости сессии делается тем же запросом, которым достаётся пользователь.
Строки создаются только через issue_session (инвариант 9 CLAUDE.md).
"""

import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, or_, select, update

from lyra.db.models import AuthSession, SessionRevokeReason, User
from lyra.db.repositories.base import BaseRepository


class SessionRepository(BaseRepository):
    async def create(
        self,
        tenant_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        refresh_hash: str,
        expires_at: datetime,
        now: datetime,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> AuthSession:
        session = AuthSession(
            tenant_id=tenant_id,
            user_id=user_id,
            refresh_hash=refresh_hash,
            expires_at=expires_at,
            last_used_at=now,
            user_agent=user_agent,
            ip=ip,
        )
        self.session.add(session)
        await self.session.flush()
        return session

    async def get(self, tenant_id: uuid.UUID, session_id: uuid.UUID) -> AuthSession | None:
        result = await self.session.execute(
            select(AuthSession).where(
                AuthSession.tenant_id == tenant_id, AuthSession.id == session_id
            )
        )
        return result.scalar_one_or_none()

    async def get_user_for_live_session(
        self, tenant_id: uuid.UUID, session_id: uuid.UUID, *, now: datetime
    ) -> User | None:
        """Пользователь, если сессия существует, не отозвана и не истекла.

        Один запрос вместо двух: current_user всё равно ходил за пользователем,
        проверка отзыва встраивается в него join'ом (ADR-012).
        """
        result = await self.session.execute(
            select(User)
            .join(AuthSession, AuthSession.user_id == User.id)
            .where(
                AuthSession.tenant_id == tenant_id,
                AuthSession.id == session_id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
            )
        )
        return result.scalar_one_or_none()

    async def rotate(
        self,
        tenant_id: uuid.UUID,
        session_id: uuid.UUID,
        *,
        refresh_hash: str,
        expires_at: datetime,
        now: datetime,
    ) -> None:
        """Переписывает refresh-хеш и продлевает скользящее окно."""
        await self.session.execute(
            update(AuthSession)
            .where(AuthSession.tenant_id == tenant_id, AuthSession.id == session_id)
            .values(refresh_hash=refresh_hash, expires_at=expires_at, last_used_at=now)
        )

    async def revoke(
        self,
        tenant_id: uuid.UUID,
        session_id: uuid.UUID,
        *,
        reason: SessionRevokeReason,
        now: datetime,
    ) -> int:
        """Отзыв идемпотентен: повторный вызов не переписывает причину."""
        result = await self.session.execute(
            update(AuthSession)
            .where(
                AuthSession.tenant_id == tenant_id,
                AuthSession.id == session_id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=now, revoked_reason=reason)
        )
        return cast(CursorResult[Any], result).rowcount or 0

    async def revoke_all_for_user(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        reason: SessionRevokeReason,
        now: datetime,
        keep_session_id: uuid.UUID | None = None,
    ) -> int:
        """«Выйти на всех устройствах»; keep_session_id оставляет текущую."""
        query = (
            update(AuthSession)
            .where(
                AuthSession.tenant_id == tenant_id,
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=now, revoked_reason=reason)
        )
        if keep_session_id is not None:
            query = query.where(AuthSession.id != keep_session_id)
        result = await self.session.execute(query)
        return cast(CursorResult[Any], result).rowcount or 0

    async def list_active_for_user(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, *, now: datetime
    ) -> list[AuthSession]:
        result = await self.session.execute(
            select(AuthSession)
            .where(
                AuthSession.tenant_id == tenant_id,
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
            )
            .order_by(AuthSession.last_used_at.desc())
        )
        return list(result.scalars())

    async def delete_dead(self, tenant_id: uuid.UUID, *, before: datetime) -> int:
        """Чистка: истёкшие и отозванные до указанного момента."""
        result = await self.session.execute(
            delete(AuthSession).where(
                AuthSession.tenant_id == tenant_id,
                or_(AuthSession.expires_at < before, AuthSession.revoked_at < before),
            )
        )
        return cast(CursorResult[Any], result).rowcount or 0
