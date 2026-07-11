"""Репозиторий пользователей."""

import uuid

from sqlalchemy import func, select

from lyra.db.models import User, UserRole
from lyra.db.repositories.base import BaseRepository


class UserRepository(BaseRepository):
    async def get(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User | None:
        result = await self.session.execute(
            select(User).where(User.tenant_id == tenant_id, User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, tenant_id: uuid.UUID, email: str) -> User | None:
        result = await self.session.execute(
            select(User).where(User.tenant_id == tenant_id, User.email == email)
        )
        return result.scalar_one_or_none()

    async def list(
        self, tenant_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[User], int]:
        rows = await self.session.execute(
            select(User)
            .where(User.tenant_id == tenant_id)
            .order_by(User.created_at)
            .limit(limit)
            .offset(offset)
        )
        total = await self.session.scalar(
            select(func.count()).select_from(User).where(User.tenant_id == tenant_id)
        )
        return list(rows.scalars()), total or 0

    async def create(
        self,
        tenant_id: uuid.UUID,
        *,
        email: str,
        password_hash: str,
        role: UserRole,
    ) -> User:
        user = User(tenant_id=tenant_id, email=email, password_hash=password_hash, role=role)
        self.session.add(user)
        await self.session.flush()
        return user

    async def update(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        role: UserRole | None = None,
        is_active: bool | None = None,
        password_hash: str | None = None,
    ) -> User | None:
        user = await self.get(tenant_id, user_id)
        if user is None:
            return None
        if role is not None:
            user.role = role
        if is_active is not None:
            user.is_active = is_active
        if password_hash is not None:
            user.password_hash = password_hash
        await self.session.flush()
        return user
