"""Схемы ingest-эндпоинтов (docs/api-contract.md §2)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from lyra.db.models import (
    DocumentStatus,
    IngestJobKind,
    IngestJobStatus,
    SourceStatus,
    SourceType,
)


class UploadAccepted(BaseModel):
    job_id: uuid.UUID
    document_id: uuid.UUID
    status: IngestJobStatus


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: IngestJobKind
    status: IngestJobStatus
    steps: dict[str, Any]
    error: str | None
    source_id: uuid.UUID | None
    document_version_id: uuid.UUID | None
    created_at: datetime


class JobsPage(BaseModel):
    items: list[JobOut]
    total: int


class SourceCreate(BaseModel):
    collection_id: uuid.UUID
    type: SourceType
    name: str = Field(min_length=1)
    # Секреты — только ссылкой token_secret_ref на env-переменную
    config: dict[str, Any] = Field(default_factory=dict)
    sync_schedule: str | None = None


class SourcePatch(BaseModel):
    name: str | None = None
    config: dict[str, Any] | None = None
    sync_schedule: str | None = None
    status: SourceStatus | None = None


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    collection_id: uuid.UUID
    type: SourceType
    name: str
    config: dict[str, Any]
    sync_schedule: str | None
    sync_cursor: dict[str, Any] | None
    status: SourceStatus


class SourcesPage(BaseModel):
    items: list[SourceOut]
    total: int


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_id: uuid.UUID
    external_id: str
    title: str
    url: str | None
    author: str | None
    status: DocumentStatus
    active_version_id: uuid.UUID | None
    created_at: datetime


class DocumentsPage(BaseModel):
    items: list[DocumentOut]
    total: int


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: int
    content_hash: str
    status: str
    created_at: datetime


class DocumentDetail(DocumentOut):
    versions: list[VersionOut]


class ReindexRequest(BaseModel):
    collection_id: uuid.UUID


class SyncAccepted(BaseModel):
    source_id: uuid.UUID
    status: str = "queued"
