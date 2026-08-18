"""Тенанты, пользователи и сессии входа (docs/data-model.md §2)."""

import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import CITEXT, INET
from sqlalchemy.orm import Mapped, mapped_column

from lyra.db.base import Base, IdTimestampMixin, TenantMixin
from lyra.db.models.enums import SessionRevokeReason, TenantStatus, UserRole


class Tenant(IdTimestampMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(Text)
    status: Mapped[TenantStatus] = mapped_column(
        Enum(TenantStatus, name="tenant_status", values_callable=lambda e: [m.value for m in e]),
        default=TenantStatus.ACTIVE,
    )


class User(IdTimestampMixin, TenantMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=lambda e: [m.value for m in e]),
        default=UserRole.VIEWER,
    )
    is_active: Mapped[bool] = mapped_column(default=True)


class AuthSession(IdTimestampMixin, TenantMixin, Base):
    """Сессия входа — единица отзыва доступа (ADR-012).

    Названа AuthSession, а не Session: в коде `session` — это AsyncSession,
    а ChatSession — уже занятое имя из другой предметной области.

    Создаётся только через `issue_session` (инвариант 9 CLAUDE.md).
    """

    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_expires_at", "expires_at"),
        Index("ix_sessions_user_active", "user_id", "revoked_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    # sha256 от refresh-токена: дамп БД не даёт войти
    refresh_hash: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime]
    last_used_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    revoked_reason: Mapped[SessionRevokeReason | None] = mapped_column(
        Enum(
            SessionRevokeReason,
            name="session_revoke_reason",
            values_callable=lambda e: [m.value for m in e],
        )
    )
    # Справочные поля для списка «мои устройства»; средством аутентификации
    # не являются и ни на что не влияют
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(INET)
