"""Источники и ingest-jobs (docs/api-contract.md §2)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from lyra.api.deps import LimitDep, OffsetDep, SessionDep, require_role
from lyra.api.schemas.ingest import (
    JobOut,
    JobsPage,
    SourceCreate,
    SourceOut,
    SourcePatch,
    SourcesPage,
    SyncAccepted,
    public_config,
    validate_source_config,
)
from lyra.core.constants import DEFAULT_TENANT_ID
from lyra.core.errors import NotFoundError
from lyra.db.models import IngestJobStatus, Source, SourceStatus, User, UserRole
from lyra.db.repositories import IngestJobRepository, SourceRepository
from lyra.workers.tasks.ingest import sync_source

router = APIRouter(tags=["sources"])

ViewerDep = Annotated[User, Depends(require_role(UserRole.VIEWER))]
EDITOR = Depends(require_role(UserRole.EDITOR))


def _source_out(source: Source, user: User) -> SourceOut:
    """config целиком — только admin: email и token_secret_ref описывают
    внутренний контур и viewer'у не предназначены (security-and-access §5)."""
    out = SourceOut.model_validate(source)
    if user.role is not UserRole.ADMIN:
        out.config = public_config(out.config)
    return out


@router.get("/sources")
async def list_sources(
    session: SessionDep,
    user: ViewerDep,
    collection_id: uuid.UUID | None = None,
    limit: LimitDep = 50,
    offset: OffsetDep = 0,
) -> SourcesPage:
    sources, total = await SourceRepository(session).list(
        DEFAULT_TENANT_ID, collection_id=collection_id, limit=limit, offset=offset
    )
    return SourcesPage(items=[_source_out(s, user) for s in sources], total=total)


@router.post("/sources", status_code=201)
async def create_source(
    body: SourceCreate, session: SessionDep, user: Annotated[User, EDITOR]
) -> SourceOut:
    validate_source_config(body.type, body.config)
    source = await SourceRepository(session).create(
        DEFAULT_TENANT_ID,
        collection_id=body.collection_id,
        type_=body.type,
        name=body.name,
        config=body.config,
        sync_schedule=body.sync_schedule,
    )
    await session.commit()
    return _source_out(source, user)


@router.get("/sources/{source_id}")
async def get_source(source_id: uuid.UUID, session: SessionDep, user: ViewerDep) -> SourceOut:
    source = await SourceRepository(session).get(DEFAULT_TENANT_ID, source_id)
    if source is None:
        raise NotFoundError("Источник не найден")
    return _source_out(source, user)


@router.patch("/sources/{source_id}")
async def patch_source(
    source_id: uuid.UUID,
    body: SourcePatch,
    session: SessionDep,
    user: Annotated[User, EDITOR],
) -> SourceOut:
    repo = SourceRepository(session)
    if body.config is not None:
        existing = await repo.get(DEFAULT_TENANT_ID, source_id)
        if existing is None:
            raise NotFoundError("Источник не найден")
        validate_source_config(existing.type, body.config)
    source = await repo.update(
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
    return _source_out(source, user)


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
    limit: LimitDep = 50,
    offset: OffsetDep = 0,
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
