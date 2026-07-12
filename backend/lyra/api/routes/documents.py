"""Загрузка и просмотр документов (docs/api-contract.md §2).

POST /documents/upload синхронно только сохраняет файл, создаёт job и ставит
Celery-задачу (FR-2) — парсинг/эмбеддинг в API-процессе запрещены.
"""

import os
import uuid

from fastapi import APIRouter, Depends, UploadFile

from lyra.api.deps import SessionDep, require_role
from lyra.api.schemas.ingest import DocumentDetail, DocumentOut, UploadAccepted, VersionOut
from lyra.core.config import get_settings
from lyra.core.constants import DEFAULT_TENANT_ID
from lyra.core.errors import LyraError, NotFoundError
from lyra.db.models import DocumentStatus, IngestJobKind, SourceType, UserRole
from lyra.db.repositories import DocumentRepository, IngestJobRepository, SourceRepository
from lyra.ingest.parsers import detect_format
from lyra.workers.tasks.ingest import process_upload

router = APIRouter(tags=["documents"])


class PayloadTooLarge(LyraError):
    code = "payload_too_large"
    status_code = 413


class UnsupportedFileType(LyraError):
    code = "unsupported_file_type"
    status_code = 415


@router.post(
    "/documents/upload",
    status_code=202,
    dependencies=[Depends(require_role(UserRole.EDITOR))],
)
async def upload_document(
    file: UploadFile, collection_id: uuid.UUID, session: SessionDep
) -> UploadAccepted:
    settings = get_settings()
    content = await file.read()
    if len(content) > settings.upload_max_bytes:
        raise PayloadTooLarge(f"Файл больше {settings.upload_max_bytes // (1024 * 1024)} МБ")
    filename = file.filename or "upload.txt"
    fmt = detect_format(content, filename)
    if fmt is None:
        raise UnsupportedFileType("Поддерживаются PDF, DOCX, Markdown, TXT")

    tenant_id = DEFAULT_TENANT_ID
    sources = SourceRepository(session)
    documents = DocumentRepository(session)

    # Неявный upload-source коллекции (api-contract §2)
    source = await sources.get_upload_source(tenant_id, collection_id)
    if source is None:
        source = await sources.create(
            tenant_id,
            collection_id=collection_id,
            type_=SourceType.UPLOAD,
            name="Загрузки",
        )
    document = await documents.get_by_external_id(
        tenant_id, source.id, filename
    ) or await documents.create(
        tenant_id, source_id=source.id, external_id=filename, title=filename
    )

    # Файл хранится по id документа — реиндекс и повторные версии находят его
    os.makedirs(settings.upload_dir, exist_ok=True)
    file_path = os.path.join(settings.upload_dir, str(document.id))
    with open(file_path, "wb") as fh:
        fh.write(content)

    job = await IngestJobRepository(session).create(
        tenant_id, kind=IngestJobKind.UPLOAD, source_id=source.id
    )
    await session.commit()
    task = process_upload.delay(str(job.id), str(document.id), file_path, filename, fmt)
    await IngestJobRepository(session).update_status(
        tenant_id, job.id, status=job.status, celery_task_id=task.id
    )
    await session.commit()
    return UploadAccepted(job_id=job.id, document_id=document.id, status=job.status)


@router.get("/documents", dependencies=[Depends(require_role(UserRole.VIEWER))])
async def list_documents(
    session: SessionDep,
    source_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[DocumentOut]:
    documents = await DocumentRepository(session).list(
        DEFAULT_TENANT_ID, source_id=source_id, limit=limit, offset=offset
    )
    return [DocumentOut.model_validate(d) for d in documents]


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
