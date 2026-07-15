"""Репозиторий документов и версий.

Ключевой метод — activate_version: атомарное переключение видимой версии
(инвариант docs/data-model.md §3). Блокировка строки документа (FOR UPDATE)
сериализует конкурентные активации — двух active-версий не бывает.
"""

import uuid
from datetime import datetime

from sqlalchemy import func, select, update

from lyra.db.models import Document, DocumentVersion, VersionStatus
from lyra.db.repositories.base import BaseRepository


class DocumentRepository(BaseRepository):
    async def get(self, tenant_id: uuid.UUID, document_id: uuid.UUID) -> Document | None:
        result = await self.session.execute(
            select(Document).where(Document.tenant_id == tenant_id, Document.id == document_id)
        )
        return result.scalar_one_or_none()

    async def get_by_external_id(
        self, tenant_id: uuid.UUID, source_id: uuid.UUID, external_id: str
    ) -> Document | None:
        result = await self.session.execute(
            select(Document).where(
                Document.tenant_id == tenant_id,
                Document.source_id == source_id,
                Document.external_id == external_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        tenant_id: uuid.UUID,
        *,
        source_id: uuid.UUID,
        external_id: str,
        title: str,
        url: str | None = None,
        author: str | None = None,
    ) -> Document:
        document = Document(
            tenant_id=tenant_id,
            source_id=source_id,
            external_id=external_id,
            title=title,
            url=url,
            author=author,
        )
        self.session.add(document)
        await self.session.flush()
        return document

    async def create_version(
        self,
        tenant_id: uuid.UUID,
        *,
        document_id: uuid.UUID,
        content_hash: str,
        source_updated_at: datetime | None = None,
    ) -> DocumentVersion:
        """Новая версия со следующим номером; unique (document_id, content_hash)
        отсекает дубликат содержимого на уровне БД."""
        last = await self.session.scalar(
            select(DocumentVersion.version)
            .where(
                DocumentVersion.tenant_id == tenant_id,
                DocumentVersion.document_id == document_id,
            )
            .order_by(DocumentVersion.version.desc())
            .limit(1)
        )
        version = DocumentVersion(
            tenant_id=tenant_id,
            document_id=document_id,
            version=(last or 0) + 1,
            content_hash=content_hash,
            source_updated_at=source_updated_at,
        )
        self.session.add(version)
        await self.session.flush()
        return version

    async def find_version_by_hash(
        self, tenant_id: uuid.UUID, document_id: uuid.UUID, content_hash: str
    ) -> DocumentVersion | None:
        result = await self.session.execute(
            select(DocumentVersion).where(
                DocumentVersion.tenant_id == tenant_id,
                DocumentVersion.document_id == document_id,
                DocumentVersion.content_hash == content_hash,
            )
        )
        return result.scalar_one_or_none()

    async def activate_version(
        self, tenant_id: uuid.UUID, document_id: uuid.UUID, version_id: uuid.UUID
    ) -> None:
        """Атомарное переключение: new → active, прежняя → superseded.

        Вызывающий код коммитит транзакцию целиком; при откате состояние
        не меняется. FOR UPDATE на documents сериализует гонку активаций.
        """
        await self.session.execute(
            select(Document.id)
            .where(Document.tenant_id == tenant_id, Document.id == document_id)
            .with_for_update()
        )
        await self.session.execute(
            update(DocumentVersion)
            .where(
                DocumentVersion.tenant_id == tenant_id,
                DocumentVersion.document_id == document_id,
                DocumentVersion.status == VersionStatus.ACTIVE,
                DocumentVersion.id != version_id,
            )
            .values(status=VersionStatus.SUPERSEDED)
        )
        await self.session.execute(
            update(DocumentVersion)
            .where(DocumentVersion.tenant_id == tenant_id, DocumentVersion.id == version_id)
            .values(status=VersionStatus.ACTIVE)
        )
        await self.session.execute(
            update(Document)
            .where(Document.tenant_id == tenant_id, Document.id == document_id)
            .values(active_version_id=version_id)
        )

    async def list_versions(
        self, tenant_id: uuid.UUID, document_id: uuid.UUID
    ) -> list[DocumentVersion]:
        result = await self.session.execute(
            select(DocumentVersion)
            .where(
                DocumentVersion.tenant_id == tenant_id,
                DocumentVersion.document_id == document_id,
            )
            .order_by(DocumentVersion.version)
        )
        return list(result.scalars())

    async def list(
        self,
        tenant_id: uuid.UUID,
        *,
        source_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Document]:
        query = select(Document).where(Document.tenant_id == tenant_id)
        if source_id is not None:
            query = query.where(Document.source_id == source_id)
        result = await self.session.execute(
            query.order_by(Document.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars())

    async def count(self, tenant_id: uuid.UUID, *, source_id: uuid.UUID | None = None) -> int:
        query = select(func.count()).select_from(Document).where(Document.tenant_id == tenant_id)
        if source_id is not None:
            query = query.where(Document.source_id == source_id)
        result = await self.session.execute(query)
        return int(result.scalar_one())
