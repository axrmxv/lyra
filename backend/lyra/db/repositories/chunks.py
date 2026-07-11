"""Репозиторий chunks: bulk upsert (идемпотентность шага index) и выборки.

Поиск (BM25/вектор) сюда НЕ добавляется — это retrieval-слой фазы 3
за интерфейсом VectorStore (ADR-001).
"""

import uuid
from typing import Any, cast

from sqlalchemy import CursorResult, func, select
from sqlalchemy.dialects.postgresql import insert

from lyra.db.models import Chunk, DocumentVersion, VersionStatus
from lyra.db.repositories.base import BaseRepository


class ChunkRepository(BaseRepository):
    async def bulk_upsert(self, tenant_id: uuid.UUID, chunks: list[dict[str, Any]]) -> int:
        """Вставка chunks; конфликт по (document_version_id, ordinal) — no-op.

        Повторное выполнение шага index (acks_late, ADR-008) не создаёт дублей.
        """
        if not chunks:
            return 0
        rows = [{**chunk, "tenant_id": tenant_id} for chunk in chunks]
        statement = insert(Chunk).on_conflict_do_nothing(
            index_elements=["document_version_id", "ordinal"]
        )
        result = await self.session.execute(statement, rows)
        return cast(CursorResult[Any], result).rowcount or 0

    async def count_for_version(self, tenant_id: uuid.UUID, version_id: uuid.UUID) -> int:
        total = await self.session.scalar(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.tenant_id == tenant_id, Chunk.document_version_id == version_id)
        )
        return total or 0

    async def list_visible_for_document(
        self, tenant_id: uuid.UUID, document_id: uuid.UUID
    ) -> list[Chunk]:
        """Chunks только активной версии — инвариант видимости data-model §3."""
        result = await self.session.execute(
            select(Chunk)
            .join(DocumentVersion, Chunk.document_version_id == DocumentVersion.id)
            .where(
                Chunk.tenant_id == tenant_id,
                DocumentVersion.document_id == document_id,
                DocumentVersion.status == VersionStatus.ACTIVE,
            )
            .order_by(Chunk.ordinal)
        )
        return list(result.scalars())

    async def delete_for_version(self, tenant_id: uuid.UUID, version_id: uuid.UUID) -> int:
        """Используется GC-задачей (фаза 2) для superseded-версий."""
        from sqlalchemy import delete

        result = await self.session.execute(
            delete(Chunk).where(
                Chunk.tenant_id == tenant_id, Chunk.document_version_id == version_id
            )
        )
        return cast(CursorResult[Any], result).rowcount or 0
