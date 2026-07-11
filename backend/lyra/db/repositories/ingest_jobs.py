"""Репозиторий ingest-jobs."""

import uuid
from typing import Any

from sqlalchemy import select

from lyra.db.models import IngestJob, IngestJobKind, IngestJobStatus
from lyra.db.repositories.base import BaseRepository


class IngestJobRepository(BaseRepository):
    async def get(self, tenant_id: uuid.UUID, job_id: uuid.UUID) -> IngestJob | None:
        result = await self.session.execute(
            select(IngestJob).where(IngestJob.tenant_id == tenant_id, IngestJob.id == job_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        tenant_id: uuid.UUID,
        *,
        kind: IngestJobKind,
        source_id: uuid.UUID | None = None,
        document_version_id: uuid.UUID | None = None,
    ) -> IngestJob:
        job = IngestJob(
            tenant_id=tenant_id,
            kind=kind,
            source_id=source_id,
            document_version_id=document_version_id,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def list(
        self,
        tenant_id: uuid.UUID,
        *,
        status: IngestJobStatus | None = None,
        source_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[IngestJob]:
        query = select(IngestJob).where(IngestJob.tenant_id == tenant_id)
        if status is not None:
            query = query.where(IngestJob.status == status)
        if source_id is not None:
            query = query.where(IngestJob.source_id == source_id)
        result = await self.session.execute(
            query.order_by(IngestJob.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars())

    async def update_status(
        self,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        *,
        status: IngestJobStatus,
        error: str | None = None,
        steps: dict[str, Any] | None = None,
        document_version_id: uuid.UUID | None = None,
        celery_task_id: str | None = None,
    ) -> IngestJob | None:
        job = await self.get(tenant_id, job_id)
        if job is None:
            return None
        job.status = status
        if error is not None:
            job.error = error
        if steps is not None:
            job.steps = steps
        if document_version_id is not None:
            job.document_version_id = document_version_id
        if celery_task_id is not None:
            job.celery_task_id = celery_task_id
        await self.session.flush()
        return job
