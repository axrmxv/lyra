"""Тенанты и пользователи (docs/data-model.md §2)."""

from sqlalchemy import Enum, Text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from lyra.db.base import Base, IdTimestampMixin, TenantMixin
from lyra.db.models.enums import TenantStatus, UserRole


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
