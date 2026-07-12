"""Celery-задачи ingest (ADR-008).

Каждая задача идемпотентна (acks_late): шаги пайплайна переживают повтор.
Sync-ошибки: ParserError/Permanent — job failed без retry; сетевые/EmbeddingError —
autoretry c exponential backoff + jitter (max 5).

Задачи синхронные (Celery prefork) — каждая создаёт собственный engine
на своём event loop через asyncio.run и закрывает его.
"""

import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TypeVar

import httpx
import structlog
from croniter import croniter
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lyra.core.clients.embeddings import EmbeddingError
from lyra.core.config import get_settings
from lyra.core.constants import DEFAULT_TENANT_ID
from lyra.db.models import DocumentStatus, IngestJobKind, IngestJobStatus, SourceStatus
from lyra.db.repositories import DocumentRepository, IngestJobRepository, SourceRepository
from lyra.db.session import build_engine
from lyra.ingest import service
from lyra.ingest.connectors import ConfluenceConnector
from lyra.ingest.parsers import detect_format
from lyra.ingest.service import PermanentIngestError
from lyra.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)

T = TypeVar("T")

TRANSIENT_ERRORS = (EmbeddingError, httpx.HTTPError, ConnectionError, OSError)


def _run_with_session(fn: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Свежий engine на loop задачи; dispose гарантирован."""

    async def runner() -> T:
        engine = build_engine(get_settings())
        maker = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with maker() as session:
                return await fn(session)
        finally:
            await engine.dispose()

    return asyncio.run(runner())


def _fail_job(job_id: str, error: str) -> None:
    def fail(session: AsyncSession) -> Awaitable[None]:
        return service.mark_job_failed(
            session, tenant_id=DEFAULT_TENANT_ID, job_id=uuid.UUID(job_id), error=error
        )

    _run_with_session(fail)


@celery_app.task(  # type: ignore[untyped-decorator]  # у celery нет стабов
    name="lyra.ingest.process_upload",
    queue="ingest",
    autoretry_for=TRANSIENT_ERRORS,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
    rate_limit="30/m",  # защита embeddings-сервиса (ADR-008)
)
def process_upload(job_id: str, document_id: str, file_path: str, filename: str, fmt: str) -> str:
    try:
        status = _run_with_session(
            lambda session: service.ingest_upload(
                session,
                tenant_id=DEFAULT_TENANT_ID,
                job_id=uuid.UUID(job_id),
                document_id=uuid.UUID(document_id),
                file_path=file_path,
                filename=filename,
                fmt=fmt,
            )
        )
    except PermanentIngestError as exc:
        logger.error("ingest_permanent_failure", job_id=job_id, error=str(exc))
        _fail_job(job_id, str(exc))
        return IngestJobStatus.FAILED.value
    return status.value


@celery_app.task(  # type: ignore[untyped-decorator]
    name="lyra.ingest.process_confluence_page",
    queue="ingest",
    autoretry_for=TRANSIENT_ERRORS,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
    rate_limit="30/m",
)
def process_confluence_page(job_id: str, source_id: str, external_id: str) -> str:
    async def run(session: AsyncSession) -> IngestJobStatus:
        tenant_id = DEFAULT_TENANT_ID
        sources = SourceRepository(session)
        documents = DocumentRepository(session)
        jobs = IngestJobRepository(session)

        source = await sources.get(tenant_id, uuid.UUID(source_id))
        if source is None:
            raise PermanentIngestError("Источник не найден")
        connector = ConfluenceConnector(source.config)
        raw = await connector.fetch(external_id)
        ir = connector.normalize(raw)

        document = await documents.get_by_external_id(
            tenant_id, source.id, external_id
        ) or await documents.create(
            tenant_id,
            source_id=source.id,
            external_id=external_id,
            title=raw.title,
            url=raw.url,
            author=raw.author,
        )
        document.title = raw.title  # заголовок мог измениться
        await jobs.update_status(tenant_id, uuid.UUID(job_id), status=IngestJobStatus.PROCESSING)
        await session.commit()
        return await service.ingest_ir(
            session,
            tenant_id=tenant_id,
            job_id=uuid.UUID(job_id),
            document_id=document.id,
            ir=ir,
            source_updated_at=raw.updated_at,
        )

    try:
        return _run_with_session(run).value
    except PermanentIngestError as exc:
        logger.error("confluence_page_permanent_failure", job_id=job_id, error=str(exc))
        _fail_job(job_id, str(exc))
        return IngestJobStatus.FAILED.value


@celery_app.task(  # type: ignore[untyped-decorator]
    name="lyra.ingest.sync_source",
    queue="sync",
    autoretry_for=TRANSIENT_ERRORS,
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
)
def sync_source(source_id: str) -> dict[str, int]:
    """Инкрементальная синхронизация источника: постановка per-page задач."""

    async def run(session: AsyncSession) -> dict[str, int]:
        tenant_id = DEFAULT_TENANT_ID
        sources = SourceRepository(session)
        documents = DocumentRepository(session)
        jobs = IngestJobRepository(session)

        source = await sources.get(tenant_id, uuid.UUID(source_id))
        if source is None or source.type.value != "confluence":
            return {"changed": 0, "deleted": 0}
        connector = ConfluenceConnector(source.config)
        changes = await connector.list_changes(source.sync_cursor)

        for item in changes.added_or_updated:
            job = await jobs.create(tenant_id, kind=IngestJobKind.SYNC, source_id=source.id)
            await session.commit()
            process_confluence_page.delay(str(job.id), str(source.id), item.external_id)

        for external_id in changes.deleted_external_ids:
            document = await documents.get_by_external_id(tenant_id, source.id, external_id)
            if document is not None:
                document.status = DocumentStatus.DELETED
        await sources.update(
            tenant_id, source.id, sync_cursor=changes.next_cursor, status=SourceStatus.ACTIVE
        )
        await session.commit()
        return {
            "changed": len(changes.added_or_updated),
            "deleted": len(changes.deleted_external_ids),
        }

    return _run_with_session(run)


@celery_app.task(name="lyra.ingest.sync_due_sources", queue="sync")  # type: ignore[untyped-decorator]
def sync_due_sources() -> int:
    """Beat-тик (раз в минуту): запускает sync источников по их cron-расписанию."""

    async def run(session: AsyncSession) -> int:
        tenant_id = DEFAULT_TENANT_ID
        sources, _ = await SourceRepository(session).list(tenant_id, limit=500)
        dispatched = 0
        now = datetime.now(UTC)
        for source in sources:
            if source.type.value != "confluence" or source.status != SourceStatus.ACTIVE:
                continue
            if not source.sync_schedule:
                continue
            cursor = source.sync_cursor or {}
            last_raw = cursor.get("last_sync_at")
            last = (
                datetime.fromisoformat(last_raw) if last_raw else datetime.min.replace(tzinfo=UTC)
            )
            try:
                due = croniter(source.sync_schedule, last).get_next(datetime) <= now
            except (ValueError, KeyError):
                logger.warning("bad_cron", source_id=str(source.id))
                continue
            if due:
                sync_source.delay(str(source.id))
                dispatched += 1
        return dispatched

    return _run_with_session(run)


@celery_app.task(name="lyra.ingest.gc_superseded", queue="ingest")  # type: ignore[untyped-decorator]
def gc_superseded() -> int:
    """Периодическая чистка chunks у superseded-версий."""
    removed = _run_with_session(
        lambda session: service.gc_superseded_versions(session, tenant_id=DEFAULT_TENANT_ID)
    )
    if removed:
        logger.info("gc_superseded_chunks", removed=removed)
    return removed


@celery_app.task(name="lyra.ingest.reindex_collection", queue="ingest")  # type: ignore[untyped-decorator]
def reindex_collection(collection_id: str) -> int:
    """POST /admin/reindex: новые версии всех документов коллекции.

    Confluence-источники — полный ресинк (сброс last_sync_at в курсоре).
    Upload-документы — повторный парсинг сохранённого файла из uploads;
    файл отсутствует (том пересоздавали) → документ пропускается c warning.
    """

    async def run(session: AsyncSession) -> int:
        tenant_id = DEFAULT_TENANT_ID
        sources_repo = SourceRepository(session)
        jobs = IngestJobRepository(session)
        sources, _ = await sources_repo.list(
            tenant_id, collection_id=uuid.UUID(collection_id), limit=500
        )
        dispatched = 0
        for source in sources:
            if source.type.value == "confluence":
                cursor = dict(source.sync_cursor or {})
                cursor.pop("last_sync_at", None)
                await sources_repo.update(tenant_id, source.id, sync_cursor=cursor)
                await session.commit()
                sync_source.delay(str(source.id))
                dispatched += 1
                continue
            documents = await DocumentRepository(session).list(
                tenant_id, source_id=source.id, limit=1000
            )
            for document in documents:
                file_path = os.path.join(get_settings().upload_dir, str(document.id))
                if not os.path.exists(file_path):
                    logger.warning("reindex_file_missing", document_id=str(document.id))
                    continue
                with open(file_path, "rb") as fh:
                    head = fh.read(64)
                fmt = detect_format(head, document.title)
                if fmt is None:
                    continue
                job = await jobs.create(tenant_id, kind=IngestJobKind.REINDEX, source_id=source.id)
                await session.commit()
                process_upload.delay(str(job.id), str(document.id), file_path, document.title, fmt)
                dispatched += 1
        return dispatched

    return _run_with_session(run)
