"""Репозиторий коллекций."""

import uuid
from typing import Any

from sqlalchemy import func, select

from lyra.db.models import Collection
from lyra.db.repositories.base import BaseRepository


class CollectionRepository(BaseRepository):
    async def get(self, tenant_id: uuid.UUID, collection_id: uuid.UUID) -> Collection | None:
        result = await self.session.execute(
            select(Collection).where(
                Collection.tenant_id == tenant_id, Collection.id == collection_id
            )
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, tenant_id: uuid.UUID, name: str) -> Collection | None:
        result = await self.session.execute(
            select(Collection).where(Collection.tenant_id == tenant_id, Collection.name == name)
        )
        return result.scalar_one_or_none()

    async def list(
        self, tenant_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[Collection], int]:
        rows = await self.session.execute(
            select(Collection)
            .where(Collection.tenant_id == tenant_id)
            .order_by(Collection.created_at)
            .limit(limit)
            .offset(offset)
        )
        total = await self.session.scalar(
            select(func.count()).select_from(Collection).where(Collection.tenant_id == tenant_id)
        )
        return list(rows.scalars()), total or 0

    async def create(
        self,
        tenant_id: uuid.UUID,
        *,
        name: str,
        embedding_model: str,
        description: str | None = None,
        chunking_config: dict[str, Any] | None = None,
    ) -> Collection:
        collection = Collection(
            tenant_id=tenant_id,
            name=name,
            description=description,
            embedding_model=embedding_model,
            chunking_config=chunking_config or {},
        )
        self.session.add(collection)
        await self.session.flush()
        return collection

    async def update(
        self,
        tenant_id: uuid.UUID,
        collection_id: uuid.UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        chunking_config: dict[str, Any] | None = None,
    ) -> Collection | None:
        collection = await self.get(tenant_id, collection_id)
        if collection is None:
            return None
        if name is not None:
            collection.name = name
        if description is not None:
            collection.description = description
        if chunking_config is not None:
            collection.chunking_config = chunking_config
        await self.session.flush()
        return collection
