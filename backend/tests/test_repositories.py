"""Тесты репозиториев: CRUD, уникальные ключи идемпотентности, версии."""

import asyncio
import uuid

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from lyra.core.auth import hash_password
from lyra.core.config import Settings
from lyra.db.models import (
    Collection,
    Document,
    DocumentVersion,
    Source,
    SourceType,
    UserRole,
    VersionStatus,
)
from lyra.db.repositories import (
    CollectionRepository,
    DocumentRepository,
    SourceRepository,
    UserRepository,
)

pytestmark = pytest.mark.integration


async def _make_document(
    session: AsyncSession, tenant_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    collection = await CollectionRepository(session).create(
        tenant_id, name=f"c-{uuid.uuid4().hex[:6]}", embedding_model="BAAI/bge-m3"
    )
    source = await SourceRepository(session).create(
        tenant_id, collection_id=collection.id, type_=SourceType.UPLOAD, name="upload"
    )
    document = await DocumentRepository(session).create(
        tenant_id, source_id=source.id, external_id=f"doc-{uuid.uuid4().hex[:6]}", title="Doc"
    )
    return collection.id, source.id, document.id


async def test_user_crud(db_session: AsyncSession, tenant_id: uuid.UUID) -> None:
    repo = UserRepository(db_session)
    email = f"user-{uuid.uuid4().hex[:6]}@lyra.local"
    user = await repo.create(
        tenant_id, email=email, password_hash=hash_password("secret123"), role=UserRole.VIEWER
    )
    assert (await repo.get_by_email(tenant_id, email.upper())) is not None  # citext
    updated = await repo.update(tenant_id, user.id, role=UserRole.EDITOR, is_active=False)
    assert updated is not None and updated.role == UserRole.EDITOR and not updated.is_active
    # Чужой tenant не видит пользователя (задел мультитенантности)
    assert await repo.get(uuid.uuid4(), user.id) is None


async def test_document_unique_external_id(db_session: AsyncSession, tenant_id: uuid.UUID) -> None:
    _, source_id, _ = await _make_document(db_session, tenant_id)
    repo = DocumentRepository(db_session)
    await repo.create(tenant_id, source_id=source_id, external_id="dup", title="A")
    with pytest.raises(IntegrityError):
        await repo.create(tenant_id, source_id=source_id, external_id="dup", title="B")


async def test_version_unique_content_hash(db_session: AsyncSession, tenant_id: uuid.UUID) -> None:
    _, _, document_id = await _make_document(db_session, tenant_id)
    repo = DocumentRepository(db_session)
    v1 = await repo.create_version(tenant_id, document_id=document_id, content_hash="h1")
    assert v1.version == 1
    assert await repo.find_version_by_hash(tenant_id, document_id, "h1") is not None
    with pytest.raises(IntegrityError):
        await repo.create_version(tenant_id, document_id=document_id, content_hash="h1")


async def test_activate_version_switches_atomically(
    db_session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    _, _, document_id = await _make_document(db_session, tenant_id)
    repo = DocumentRepository(db_session)
    v1 = await repo.create_version(tenant_id, document_id=document_id, content_hash="h1")
    await repo.activate_version(tenant_id, document_id, v1.id)
    v2 = await repo.create_version(tenant_id, document_id=document_id, content_hash="h2")
    await repo.activate_version(tenant_id, document_id, v2.id)

    document = await repo.get(tenant_id, document_id)
    assert document is not None and document.active_version_id == v2.id
    result = await db_session.execute(
        select(DocumentVersion).where(DocumentVersion.document_id == document_id)
    )
    statuses = {v.content_hash: v.status for v in result.scalars()}
    assert statuses == {"h1": VersionStatus.SUPERSEDED, "h2": VersionStatus.ACTIVE}


async def test_concurrent_activation_single_active(
    migrated_db: Settings, tenant_id: uuid.UUID
) -> None:
    """Гонка активаций из двух соединений: активной остаётся ровно одна версия."""
    dsn = migrated_db.database_dsn.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(dsn)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async with maker() as setup:
        collection_id, source_id, document_id = await _make_document(setup, tenant_id)
        repo = DocumentRepository(setup)
        v1 = await repo.create_version(tenant_id, document_id=document_id, content_hash="c1")
        v2 = await repo.create_version(tenant_id, document_id=document_id, content_hash="c2")
        await setup.commit()

    async def activate(version_id: uuid.UUID) -> None:
        async with maker() as session:
            await DocumentRepository(session).activate_version(tenant_id, document_id, version_id)
            await session.commit()

    try:
        await asyncio.gather(activate(v1.id), activate(v2.id))
        async with maker() as check:
            result = await check.execute(
                select(DocumentVersion).where(
                    DocumentVersion.document_id == document_id,
                    DocumentVersion.status == VersionStatus.ACTIVE,
                )
            )
            active = list(result.scalars())
            assert len(active) == 1
            document = await DocumentRepository(check).get(tenant_id, document_id)
            assert document is not None
            assert document.active_version_id == active[0].id
            # Тест работает вне транзакционной фикстуры — подчищаем документ
            await check.execute(
                update(Document).where(Document.id == document_id).values(active_version_id=None)
            )
            await check.execute(
                delete(DocumentVersion).where(DocumentVersion.document_id == document_id)
            )
            await check.execute(delete(Document).where(Document.id == document_id))
            await check.execute(delete(Source).where(Source.id == source_id))
            await check.execute(delete(Collection).where(Collection.id == collection_id))
            await check.commit()
    finally:
        await engine.dispose()
