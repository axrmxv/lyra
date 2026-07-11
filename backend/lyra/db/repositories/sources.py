"""Репозиторий источников."""

import uuid
from typing import Any

from sqlalchemy import func, select

from lyra.db.models import Source, SourceStatus, SourceType
from lyra.db.repositories.base import BaseRepository


class SourceRepository(BaseRepository):
    async def get(self, tenant_id: uuid.UUID, source_id: uuid.UUID) -> Source | None:
        result = await self.session.execute(
            select(Source).where(Source.tenant_id == tenant_id, Source.id == source_id)
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        tenant_id: uuid.UUID,
        *,
        collection_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Source], int]:
        where = [Source.tenant_id == tenant_id]
        if collection_id is not None:
            where.append(Source.collection_id == collection_id)
        rows = await self.session.execute(
            select(Source).where(*where).order_by(Source.created_at).limit(limit).offset(offset)
        )
        total = await self.session.scalar(select(func.count()).select_from(Source).where(*where))
        return list(rows.scalars()), total or 0

    async def get_upload_source(
        self, tenant_id: uuid.UUID, collection_id: uuid.UUID
    ) -> Source | None:
        """Неявный upload-source коллекции (docs/api-contract.md §2)."""
        result = await self.session.execute(
            select(Source).where(
                Source.tenant_id == tenant_id,
                Source.collection_id == collection_id,
                Source.type == SourceType.UPLOAD,
            )
        )
        return result.scalars().first()

    async def create(
        self,
        tenant_id: uuid.UUID,
        *,
        collection_id: uuid.UUID,
        type_: SourceType,
        name: str,
        config: dict[str, Any] | None = None,
        sync_schedule: str | None = None,
    ) -> Source:
        source = Source(
            tenant_id=tenant_id,
            collection_id=collection_id,
            type=type_,
            name=name,
            config=config or {},
            sync_schedule=sync_schedule,
        )
        self.session.add(source)
        await self.session.flush()
        return source

    async def update(
        self,
        tenant_id: uuid.UUID,
        source_id: uuid.UUID,
        *,
        name: str | None = None,
        config: dict[str, Any] | None = None,
        sync_schedule: str | None = None,
        sync_cursor: dict[str, Any] | None = None,
        status: SourceStatus | None = None,
    ) -> Source | None:
        source = await self.get(tenant_id, source_id)
        if source is None:
            return None
        if name is not None:
            source.name = name
        if config is not None:
            source.config = config
        if sync_schedule is not None:
            source.sync_schedule = sync_schedule
        if sync_cursor is not None:
            source.sync_cursor = sync_cursor
        if status is not None:
            source.status = status
        await self.session.flush()
        return source
