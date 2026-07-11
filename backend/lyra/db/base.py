"""Декларативная база и общие миксины моделей (docs/data-model.md §2).

Все таблицы: id (uuid7), created_at, updated_at. Доменные таблицы дополнительно
несут tenant_id — задел мультитенантности (enforcement выключен в MVP,
docs/security-and-access.md §4).
"""

import uuid
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from uuid6 import uuid7


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[type, Any]] = {
        uuid.UUID: Uuid(as_uuid=True),
        datetime: DateTime(timezone=True),
    }


class IdTimestampMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class TenantMixin:
    """tenant_id обязателен во всех доменных таблицах с первого дня (PRD A-7)."""

    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
