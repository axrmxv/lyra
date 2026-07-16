"""Ядро ingest-пайплайна: parse → scan → dedup → chunk → embed → index → activate.

Вызывается из Celery-задач (workers/tasks/ingest.py). Каждый шаг идемпотентен:
- дубликат содержимого отсекается по content_hash до эмбеддинга;
- повторная вставка chunks — no-op (unique document_version_id+ordinal);
- активация версии атомарна и повторяема.
Шаги и длительности пишутся в ingest_jobs.steps.
"""

import time
import uuid
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lyra.core.clients import EmbeddingClient
from lyra.core.config import get_settings
from lyra.core.metrics import INDEX_CHUNKS, INGEST_STEP_SECONDS
from lyra.db.models import Chunk, DocumentVersion, IngestJobStatus, VersionStatus
from lyra.db.repositories import (
    ChunkRepository,
    CollectionRepository,
    DocumentRepository,
    IngestJobRepository,
    SourceRepository,
)
from lyra.ingest.chunker import chunk_document
from lyra.ingest.ir import DocumentIR
from lyra.ingest.parsers import ParserError, parse_document
from lyra.ingest.secrets_scan import scan_text

logger = structlog.get_logger(__name__)


class PermanentIngestError(Exception):
    """Ошибка, которую не лечит retry: job → failed (ADR-008)."""


class StepTracker:
    def __init__(self) -> None:
        self.steps: dict[str, Any] = {}
        self._started: dict[str, float] = {}

    def start(self, name: str) -> None:
        self._started[name] = time.monotonic()
        self.steps[name] = {"status": "processing"}

    def done(self, name: str, **extra: Any) -> None:
        duration_ms = int((time.monotonic() - self._started.get(name, time.monotonic())) * 1000)
        self.steps[name] = {"status": "completed", "duration_ms": duration_ms, **extra}
        INGEST_STEP_SECONDS.labels(step=name).observe(duration_ms / 1000)


async def ingest_ir(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    job_id: uuid.UUID,
    document_id: uuid.UUID,
    ir: DocumentIR,
    source_updated_at: datetime | None = None,
) -> IngestJobStatus:
    """Общая часть пайплайна после парсинга (upload и sync сходятся здесь)."""
    settings = get_settings()
    jobs = IngestJobRepository(session)
    documents = DocumentRepository(session)
    chunks_repo = ChunkRepository(session)
    tracker = StepTracker()

    async def update_job(status: IngestJobStatus, **kwargs: Any) -> None:
        await jobs.update_status(tenant_id, job_id, status=status, steps=tracker.steps, **kwargs)
        await session.commit()

    document = await documents.get(tenant_id, document_id)
    if document is None:
        raise PermanentIngestError(f"Документ {document_id} не найден")
    source = await SourceRepository(session).get(tenant_id, document.source_id)
    if source is None:
        raise PermanentIngestError("Источник документа не найден")
    collection = await CollectionRepository(session).get(tenant_id, source.collection_id)
    if collection is None:
        raise PermanentIngestError("Коллекция источника не найдена")

    # --- scan: секреты не попадают в индекс (FR-6) ---
    tracker.start("scan")
    all_text = "\n".join(
        block.text for _, section in ir.iter_sections() for block in section.blocks
    )
    findings = scan_text(all_text)
    if findings:
        tracker.done("scan", findings=[f.kind for f in findings])
        logger.warning(
            "ingest_secrets_found",
            document_id=str(document_id),
            kinds=[f.kind for f in findings],
        )
        await update_job(
            IngestJobStatus.FAILED_PII,
            error=f"Обнаружены секреты: {', '.join(sorted({f.kind for f in findings}))}",
        )
        return IngestJobStatus.FAILED_PII
    tracker.done("scan")

    # --- dedup: идемпотентность по content_hash ДО эмбеддинга ---
    tracker.start("dedup")
    content_hash = ir.content_hash()
    existing = await documents.find_version_by_hash(tenant_id, document_id, content_hash)
    if existing is not None and existing.status != VersionStatus.INDEXING:
        # Версия уже доведена до конца (active/superseded/failed) — дубликат
        tracker.done("dedup", content_hash=content_hash)
        await update_job(IngestJobStatus.SKIPPED_DUPLICATE, document_version_id=existing.id)
        return IngestJobStatus.SKIPPED_DUPLICATE
    tracker.done("dedup", content_hash=content_hash, resumed=existing is not None)

    # --- версия (redelivery после падения возобновляет indexing-версию) ---
    if existing is not None:
        version = existing
    else:
        try:
            version = await documents.create_version(
                tenant_id,
                document_id=document_id,
                content_hash=content_hash,
                source_updated_at=source_updated_at,
            )
            await session.commit()
        except IntegrityError:
            # Гонка двух параллельных доставок: версию создал конкурент —
            # он же и доведёт её; этот экземпляр отдаёт дубликат
            await session.rollback()
            await update_job(IngestJobStatus.SKIPPED_DUPLICATE)
            return IngestJobStatus.SKIPPED_DUPLICATE

    # --- chunk ---
    tracker.start("chunk")
    drafts = chunk_document(
        ir,
        chunking_config=collection.chunking_config,
        doc_meta={
            "url": document.url,
            "source_updated_at": source_updated_at.isoformat() if source_updated_at else None,
        },
    )
    if not drafts:
        raise PermanentIngestError("После chunking не осталось содержимого")
    tracker.done("chunk", chunks=len(drafts))

    # --- embed (transient-ошибки пробрасываются — Celery ретраит) ---
    tracker.start("embed")
    client = EmbeddingClient(settings.embeddings_url, batch_size=settings.embedding_batch_size)
    vectors = await client.embed([draft.text for draft in drafts])
    tracker.done("embed", vectors=len(vectors))

    # --- index: одна транзакция chunks + активация версии ---
    tracker.start("index")
    await chunks_repo.bulk_upsert(
        tenant_id,
        [
            {
                "document_version_id": version.id,
                "collection_id": collection.id,
                "ordinal": draft.ordinal,
                "text": draft.text,
                "embedding": vector,
                "token_count": draft.token_count,
                "meta": draft.metadata,
            }
            for draft, vector in zip(drafts, vectors, strict=True)
        ],
    )
    await documents.activate_version(tenant_id, document_id, version.id)
    tracker.done("index")
    await update_job(IngestJobStatus.COMPLETED, document_version_id=version.id)
    # Размер индекса (FR-20): chunks активных версий
    active_chunks = await session.scalar(
        select(func.count())
        .select_from(Chunk)
        .join(DocumentVersion, Chunk.document_version_id == DocumentVersion.id)
        .where(DocumentVersion.status == VersionStatus.ACTIVE)
    )
    INDEX_CHUNKS.set(int(active_chunks or 0))
    logger.info(
        "ingest_completed",
        document_id=str(document_id),
        version=version.version,
        chunks=len(drafts),
    )
    return IngestJobStatus.COMPLETED


async def ingest_upload(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    job_id: uuid.UUID,
    document_id: uuid.UUID,
    file_path: str,
    filename: str,
    fmt: str,
) -> IngestJobStatus:
    jobs = IngestJobRepository(session)
    await jobs.update_status(tenant_id, job_id, status=IngestJobStatus.PROCESSING)
    await session.commit()

    try:
        with open(file_path, "rb") as fh:
            content = fh.read()
    except OSError as exc:
        raise PermanentIngestError(f"Файл загрузки не найден: {exc}") from exc

    try:
        ir = parse_document(content, fmt=fmt, title=filename)
    except ParserError as exc:
        raise PermanentIngestError(str(exc)) from exc

    return await ingest_ir(
        session, tenant_id=tenant_id, job_id=job_id, document_id=document_id, ir=ir
    )


async def mark_job_failed(
    session: AsyncSession, *, tenant_id: uuid.UUID, job_id: uuid.UUID, error: str
) -> None:
    await IngestJobRepository(session).update_status(
        tenant_id, job_id, status=IngestJobStatus.FAILED, error=error
    )
    await session.commit()


async def gc_superseded_versions(session: AsyncSession, *, tenant_id: uuid.UUID) -> int:
    """Удаляет chunks версий superseded — отложенная чистка (data-model §3)."""
    result = await session.execute(
        select(DocumentVersion.id)
        .join(Chunk, Chunk.document_version_id == DocumentVersion.id)
        .where(
            DocumentVersion.tenant_id == tenant_id,
            DocumentVersion.status == VersionStatus.SUPERSEDED,
        )
        .distinct()
    )
    removed = 0
    chunks_repo = ChunkRepository(session)
    for (version_id,) in result.all():
        removed += await chunks_repo.delete_for_version(tenant_id, version_id)
    await session.commit()
    return removed
