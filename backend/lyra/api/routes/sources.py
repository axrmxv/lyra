"""Источники и ingest-jobs (docs/api-contract.md §2)."""

import uuid

from fastapi import APIRouter, Depends

from lyra.api.deps import SessionDep, require_role
from lyra.api.schemas.ingest import (
    JobOut,
    JobsPage,
    SourceCreate,
    SourceOut,
    SourcePatch,
    SourcesPage,
    SyncAccepted,
)
from lyra.core.constants import DEFAULT_TENANT_ID
from lyra.core.errors import NotFoundError
from lyra.db.models import IngestJobStatus, SourceStatus, UserRole
from lyra.db.repositories import IngestJobRepository, SourceRepository
from lyra.workers.tasks.ingest import sync_source

router = APIRouter(tags=["sources"])

VIEWER = Depends(require_role(UserRole.VIEWER))
EDITOR = Depends(require_role(UserRole.EDITOR))


@router.get("/sources", dependencies=[VIEWER])
async def list_sources(
    session: SessionDep,
    collection_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> SourcesPage:
    sources, total = await SourceRepository(session).list(
        DEFAULT_TENANT_ID, collection_id=collection_id, limit=limit, offset=offset
    )
    return SourcesPage(items=[SourceOut.model_validate(s) for s in sources], total=total)


@router.post("/sources", status_code=201, dependencies=[EDITOR])
async def create_source(body: SourceCreate, session: SessionDep) -> SourceOut:
    source = await SourceRepository(session).create(
        DEFAULT_TENANT_ID,
        collection_id=body.collection_id,
        type_=body.type,
        name=body.name,
        config=body.config,
        sync_schedule=body.sync_schedule,
    )
    await session.commit()
    return SourceOut.model_validate(source)


@router.get("/sources/{source_id}", dependencies=[VIEWER])
async def get_source(source_id: uuid.UUID, session: SessionDep) -> SourceOut:
    source = await SourceRepository(session).get(DEFAULT_TENANT_ID, source_id)
    if source is None:
        raise NotFoundError("Источник не найден")
    return SourceOut.model_validate(source)


@router.patch("/sources/{source_id}", dependencies=[EDITOR])
async def patch_source(source_id: uuid.UUID, body: SourcePatch, session: SessionDep) -> SourceOut:
    source = await SourceRepository(session).update(
        DEFAULT_TENANT_ID,
        source_id,
        name=body.name,
        config=body.config,
        sync_schedule=body.sync_schedule,
        status=body.status,
    )
    if source is None:
        raise NotFoundError("Источник не найден")
    await session.commit()
    return SourceOut.model_validate(source)


@router.delete("/sources/{source_id}", status_code=204, dependencies=[EDITOR])
async def delete_source(source_id: uuid.UUID, session: SessionDep) -> None:
    source = await SourceRepository(session).update(
        DEFAULT_TENANT_ID, source_id, status=SourceStatus.PAUSED
    )
    if source is None:
        raise NotFoundError("Источник не найден")
    await session.commit()


@router.post("/sources/{source_id}/sync", status_code=202, dependencies=[EDITOR])
async def trigger_sync(source_id: uuid.UUID, session: SessionDep) -> SyncAccepted:
    source = await SourceRepository(session).get(DEFAULT_TENANT_ID, source_id)
    if source is None:
        raise NotFoundError("Источник не найден")
    sync_source.delay(str(source_id))
    return SyncAccepted(source_id=source_id)


@router.get("/ingest/jobs", dependencies=[EDITOR])
async def list_jobs(
    session: SessionDep,
    status: IngestJobStatus | None = None,
    source_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> JobsPage:
    jobs = await IngestJobRepository(session).list(
        DEFAULT_TENANT_ID, status=status, source_id=source_id, limit=limit, offset=offset
    )
    return JobsPage(items=[JobOut.model_validate(j) for j in jobs], total=len(jobs))


@router.get("/ingest/jobs/{job_id}", dependencies=[EDITOR])
async def get_job(job_id: uuid.UUID, session: SessionDep) -> JobOut:
    job = await IngestJobRepository(session).get(DEFAULT_TENANT_ID, job_id)
    if job is None:
        raise NotFoundError("Задача не найдена")
    return JobOut.model_validate(job)
