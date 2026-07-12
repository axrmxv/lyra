"""Интеграционные тесты ingest-пайплайна (сервисный слой, реальная БД).

EmbeddingClient и count_tokens подменяются — без TEI и модели токенайзера;
контракт с настоящим TEI проверяет live-верификация фазы.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import lyra.ingest.chunker as chunker_module
import lyra.ingest.service as service_module
from lyra.db.models import IngestJobKind, IngestJobStatus, SourceType, VersionStatus
from lyra.db.repositories import (
    ChunkRepository,
    CollectionRepository,
    DocumentRepository,
    IngestJobRepository,
    SourceRepository,
)
from lyra.ingest.ir import Block, BlockType, DocumentIR, Section
from lyra.ingest.service import ingest_ir

pytestmark = pytest.mark.integration


class FakeEmbeddingClient:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.001 * i] * 1024 for i, _ in enumerate(texts)]


@pytest.fixture(autouse=True)
def fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_module, "EmbeddingClient", FakeEmbeddingClient)
    monkeypatch.setattr(chunker_module, "count_tokens", lambda text: len(text.split()))


def make_ir(text: str, title: str = "Документ") -> DocumentIR:
    return DocumentIR(
        title=title,
        source_type="upload",
        root=Section(
            children=[
                Section(
                    heading="Раздел",
                    level=1,
                    blocks=[Block(type=BlockType.PARAGRAPH, text=text)],
                )
            ]
        ),
        meta={"format": "txt"},
    )


async def _setup(
    session: AsyncSession, tenant_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """collection, document, job."""
    collection = await CollectionRepository(session).create(
        tenant_id,
        name=f"c-{uuid.uuid4().hex[:6]}",
        embedding_model="BAAI/bge-m3",
        chunking_config={"defaults": {"target_tokens": 50, "max_tokens": 80, "overlap_tokens": 5}},
    )
    source = await SourceRepository(session).create(
        tenant_id, collection_id=collection.id, type_=SourceType.UPLOAD, name="Загрузки"
    )
    document = await DocumentRepository(session).create(
        tenant_id, source_id=source.id, external_id=f"f-{uuid.uuid4().hex[:6]}.txt", title="Док"
    )
    job = await IngestJobRepository(session).create(
        tenant_id, kind=IngestJobKind.UPLOAD, source_id=source.id
    )
    return collection.id, document.id, job.id


async def test_happy_path_indexes_chunks(db_session: AsyncSession, tenant_id: uuid.UUID) -> None:
    _, document_id, job_id = await _setup(db_session, tenant_id)
    status = await ingest_ir(
        db_session,
        tenant_id=tenant_id,
        job_id=job_id,
        document_id=document_id,
        ir=make_ir("Отпуск составляет 28 дней. Заявление подаётся за две недели."),
    )
    assert status == IngestJobStatus.COMPLETED

    document = await DocumentRepository(db_session).get(tenant_id, document_id)
    assert document is not None and document.active_version_id is not None
    chunks = await ChunkRepository(db_session).list_visible_for_document(tenant_id, document_id)
    assert chunks
    assert chunks[0].embedding is not None
    assert chunks[0].meta["doc_title"] == "Документ"
    job = await IngestJobRepository(db_session).get(tenant_id, job_id)
    assert job is not None
    assert set(job.steps) >= {"scan", "dedup", "chunk", "embed", "index"}


async def test_duplicate_content_skipped(db_session: AsyncSession, tenant_id: uuid.UUID) -> None:
    _, document_id, job_id = await _setup(db_session, tenant_id)
    ir = make_ir("Одинаковое содержимое документа.")
    assert (
        await ingest_ir(
            db_session, tenant_id=tenant_id, job_id=job_id, document_id=document_id, ir=ir
        )
        == IngestJobStatus.COMPLETED
    )
    chunks_before = await ChunkRepository(db_session).list_visible_for_document(
        tenant_id, document_id
    )

    job2 = await IngestJobRepository(db_session).create(tenant_id, kind=IngestJobKind.UPLOAD)
    status = await ingest_ir(
        db_session, tenant_id=tenant_id, job_id=job2.id, document_id=document_id, ir=ir
    )
    assert status == IngestJobStatus.SKIPPED_DUPLICATE
    chunks_after = await ChunkRepository(db_session).list_visible_for_document(
        tenant_id, document_id
    )
    assert len(chunks_after) == len(chunks_before)


async def test_new_version_supersedes_old(db_session: AsyncSession, tenant_id: uuid.UUID) -> None:
    _, document_id, job_id = await _setup(db_session, tenant_id)
    await ingest_ir(
        db_session,
        tenant_id=tenant_id,
        job_id=job_id,
        document_id=document_id,
        ir=make_ir("Версия один: отпуск 28 дней."),
    )
    job2 = await IngestJobRepository(db_session).create(tenant_id, kind=IngestJobKind.UPLOAD)
    await ingest_ir(
        db_session,
        tenant_id=tenant_id,
        job_id=job2.id,
        document_id=document_id,
        ir=make_ir("Версия два: отпуск 30 дней."),
    )

    repo = DocumentRepository(db_session)
    versions = await repo.list_versions(tenant_id, document_id)
    statuses = {v.version: v.status for v in versions}
    assert statuses == {1: VersionStatus.SUPERSEDED, 2: VersionStatus.ACTIVE}
    visible = await ChunkRepository(db_session).list_visible_for_document(tenant_id, document_id)
    assert all("30 дней" in c.text for c in visible)  # v1 невидима


async def test_secret_blocks_indexing(db_session: AsyncSession, tenant_id: uuid.UUID) -> None:
    _, document_id, job_id = await _setup(db_session, tenant_id)
    # Конкатенация — чтобы gitleaks не срабатывал на фикстуру в репозитории
    fake_key = "AKIA" + "IOSFODNN7REALKEY"
    status = await ingest_ir(
        db_session,
        tenant_id=tenant_id,
        job_id=job_id,
        document_id=document_id,
        ir=make_ir(f"Ключ: {fake_key}, никому не показывать"),
    )
    assert status == IngestJobStatus.FAILED_PII
    chunks = await ChunkRepository(db_session).list_visible_for_document(tenant_id, document_id)
    assert chunks == []
    job = await IngestJobRepository(db_session).get(tenant_id, job_id)
    assert job is not None and job.status == IngestJobStatus.FAILED_PII
    assert job.error is not None and "AKIA" not in job.error  # секрет не утёк в ошибку


async def test_redelivery_resumes_indexing_version(
    db_session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    """Смерть воркера после create_version (acks_late): повтор ДОВОДИТ версию,
    а не помечает job как дубликат."""
    _, document_id, job_id = await _setup(db_session, tenant_id)
    ir = make_ir("Содержимое, прерванное на этапе embed.")
    # Имитация первого прогона, упавшего после создания версии
    interrupted = await DocumentRepository(db_session).create_version(
        tenant_id, document_id=document_id, content_hash=ir.content_hash()
    )
    assert interrupted.status == VersionStatus.INDEXING

    status = await ingest_ir(
        db_session, tenant_id=tenant_id, job_id=job_id, document_id=document_id, ir=ir
    )
    assert status == IngestJobStatus.COMPLETED
    versions = await DocumentRepository(db_session).list_versions(tenant_id, document_id)
    assert len(versions) == 1 and versions[0].status == VersionStatus.ACTIVE
    chunks = await ChunkRepository(db_session).list_visible_for_document(tenant_id, document_id)
    assert chunks  # chunks доиндексированы, дублей версии нет


async def test_gc_removes_superseded_chunks(db_session: AsyncSession, tenant_id: uuid.UUID) -> None:
    _, document_id, job_id = await _setup(db_session, tenant_id)
    await ingest_ir(
        db_session,
        tenant_id=tenant_id,
        job_id=job_id,
        document_id=document_id,
        ir=make_ir("Старая версия."),
    )
    job2 = await IngestJobRepository(db_session).create(tenant_id, kind=IngestJobKind.UPLOAD)
    await ingest_ir(
        db_session,
        tenant_id=tenant_id,
        job_id=job2.id,
        document_id=document_id,
        ir=make_ir("Новая версия."),
    )
    removed = await service_module.gc_superseded_versions(db_session, tenant_id=tenant_id)
    assert removed >= 1
    visible = await ChunkRepository(db_session).list_visible_for_document(tenant_id, document_id)
    assert visible and all("Новая" in c.text for c in visible)
