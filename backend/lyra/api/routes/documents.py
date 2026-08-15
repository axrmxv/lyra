"""Загрузка и просмотр документов (docs/api-contract.md §2).

POST /documents/upload синхронно только сохраняет файл, создаёт job и ставит
Celery-задачу (FR-2) — парсинг/эмбеддинг в API-процессе запрещены.
"""

import contextlib
import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, UploadFile
from kombu.exceptions import OperationalError
from starlette.concurrency import run_in_threadpool

from lyra.api.deps import LimitDep, OffsetDep, SessionDep, require_role
from lyra.api.schemas.ingest import (
    DocumentDetail,
    DocumentOut,
    DocumentsPage,
    UploadAccepted,
    VersionOut,
)
from lyra.core.config import get_settings
from lyra.core.constants import DEFAULT_TENANT_ID
from lyra.core.errors import (
    NotFoundError,
    PayloadTooLargeError,
    ServiceUnavailableError,
    UnsupportedFileTypeError,
)
from lyra.db.models import DocumentStatus, IngestJobKind, UserRole
from lyra.db.repositories import DocumentRepository, IngestJobRepository, SourceRepository
from lyra.ingest.parsers import detect_format
from lyra.workers.tasks.ingest import process_upload

router = APIRouter(tags=["documents"])

# Головы файла хватает и magic bytes, и текстовой эвристике detect_format
UPLOAD_HEAD_BYTES = 4096
COPY_CHUNK_BYTES = 1024 * 1024


def _too_large(limit: int) -> PayloadTooLargeError:
    return PayloadTooLargeError(f"Файл больше {limit // (1024 * 1024)} МБ")


async def _store_upload(file: UploadFile, *, upload_dir: str, name: str, limit: int) -> str:
    """Копирование чанками в отдельном потоке (правило «async-only I/O»).

    Файл не собирается в памяти целиком, а размер считается по факту записи —
    Content-Length и UploadFile.size проверяются раньше, но авторитетен этот
    счётчик. Пишем во временное имя и подменяем os.replace: параллельная
    повторная загрузка того же документа не даст воркеру прочитать половину.
    """
    path = os.path.join(upload_dir, name)
    tmp_path = f"{path}.part"

    def write() -> None:
        os.makedirs(upload_dir, exist_ok=True)
        try:
            written = 0
            with open(tmp_path, "wb") as fh:
                while chunk := file.file.read(COPY_CHUNK_BYTES):
                    written += len(chunk)
                    if written > limit:
                        raise _too_large(limit)
                    fh.write(chunk)
            os.replace(tmp_path, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.remove(tmp_path)
            raise

    await run_in_threadpool(write)
    return path


@router.post(
    "/documents/upload",
    status_code=202,
    dependencies=[Depends(require_role(UserRole.EDITOR))],
)
async def upload_document(
    file: UploadFile,
    # multipart-поле по api-contract §2 (было query-параметром — отступление фазы 2)
    collection_id: Annotated[uuid.UUID, Form()],
    session: SessionDep,
) -> UploadAccepted:
    settings = get_settings()
    if file.size is not None and file.size > settings.upload_max_bytes:
        raise _too_large(settings.upload_max_bytes)
    filename = file.filename or "upload.txt"
    # Формат — по голове файла: содержимое целиком в память не поднимается
    fmt = detect_format(await file.read(UPLOAD_HEAD_BYTES), filename)
    if fmt is None:
        raise UnsupportedFileTypeError("Поддерживаются PDF, DOCX, Markdown, TXT")
    await file.seek(0)

    tenant_id = DEFAULT_TENANT_ID
    sources = SourceRepository(session)
    documents = DocumentRepository(session)

    # Неявный upload-source коллекции (api-contract §2)
    source = await sources.get_or_create_upload_source(tenant_id, collection_id)
    document = await documents.get_or_create_by_external_id(
        tenant_id, source_id=source.id, external_id=filename, title=filename
    )

    # Файл хранится по id документа — реиндекс и повторные версии находят его
    file_path = await _store_upload(
        file,
        upload_dir=settings.upload_dir,
        name=str(document.id),
        limit=settings.upload_max_bytes,
    )

    job = await IngestJobRepository(session).create(
        tenant_id, kind=IngestJobKind.UPLOAD, source_id=source.id
    )
    await session.commit()
    try:
        task = process_upload.delay(str(job.id), str(document.id), file_path, filename, fmt)
    except OperationalError as exc:
        # Брокер (Redis) недоступен: файл сохранён, job останется queued —
        # честная 503 вместо 500 (architecture.md §4)
        raise ServiceUnavailableError(
            "Очередь обработки недоступна, повторите загрузку позже"
        ) from exc
    # Только celery_task_id: статус к этому моменту мог уже перевести воркер
    await IngestJobRepository(session).update_status(tenant_id, job.id, celery_task_id=task.id)
    await session.commit()
    return UploadAccepted(job_id=job.id, document_id=document.id, status=job.status)


@router.get("/documents", dependencies=[Depends(require_role(UserRole.VIEWER))])
async def list_documents(
    session: SessionDep,
    source_id: uuid.UUID | None = None,
    limit: LimitDep = 50,
    offset: OffsetDep = 0,
) -> DocumentsPage:
    # Пагинация items/total — преамбула api-contract; голый список был
    # отступлением фазы 2 от контракта
    repo = DocumentRepository(session)
    documents = await repo.list(DEFAULT_TENANT_ID, source_id=source_id, limit=limit, offset=offset)
    total = await repo.count(DEFAULT_TENANT_ID, source_id=source_id)
    return DocumentsPage(items=[DocumentOut.model_validate(d) for d in documents], total=total)


@router.get("/documents/{document_id}", dependencies=[Depends(require_role(UserRole.VIEWER))])
async def get_document(document_id: uuid.UUID, session: SessionDep) -> DocumentDetail:
    repo = DocumentRepository(session)
    document = await repo.get(DEFAULT_TENANT_ID, document_id)
    if document is None:
        raise NotFoundError("Документ не найден")
    versions = [
        VersionOut.model_validate(v)
        for v in await repo.list_versions(DEFAULT_TENANT_ID, document_id)
    ]
    return DocumentDetail(**DocumentOut.model_validate(document).model_dump(), versions=versions)


@router.delete(
    "/documents/{document_id}",
    status_code=204,
    dependencies=[Depends(require_role(UserRole.EDITOR))],
)
async def delete_document(document_id: uuid.UUID, session: SessionDep) -> None:
    """Soft delete: документ исключается из выдачи (retrieval видит только active)."""
    repo = DocumentRepository(session)
    document = await repo.get(DEFAULT_TENANT_ID, document_id)
    if document is None:
        raise NotFoundError("Документ не найден")
    document.status = DocumentStatus.DELETED
    await session.commit()
