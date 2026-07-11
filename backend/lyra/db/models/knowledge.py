"""Коллекции, источники, документы, версии, chunks, ingest-jobs.

Схема — docs/data-model.md §2–4. Ключевые инварианты (§3):
- unique (source_id, external_id) — ключ документа для коннектора;
- unique (document_id, content_hash) — идемпотентность ingest;
- unique (document_version_id, ordinal) — повторная индексация шага embed/index
  безопасна (upsert, ADR-008 acks_late);
- documents.active_version_id — атомарное переключение видимой версии.
"""

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, Enum, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from lyra.db.base import Base, IdTimestampMixin, TenantMixin
from lyra.db.models.enums import (
    DocumentStatus,
    IngestJobKind,
    IngestJobStatus,
    SourceStatus,
    SourceType,
    VersionStatus,
)

EMBEDDING_DIM = 1024  # bge-m3, ADR-003; смена размерности = новая таблица + переиндексация


def _enum(enum_cls: type, name: str) -> Enum:
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


class Collection(IdTimestampMixin, TenantMixin, Base):
    __tablename__ = "collections"

    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    # Контракт индекса: имя+версия embedding-модели (ADR-003); смена → переиндексация
    embedding_model: Mapped[str] = mapped_column(Text)
    chunking_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Source(IdTimestampMixin, TenantMixin, Base):
    __tablename__ = "sources"

    collection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("collections.id"))
    type: Mapped[SourceType] = mapped_column(_enum(SourceType, "source_type"))
    name: Mapped[str] = mapped_column(Text)
    # Секреты — НЕ здесь: только ссылка token_secret_ref на env-переменную
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    sync_cursor: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    sync_schedule: Mapped[str | None] = mapped_column(Text)
    status: Mapped[SourceStatus] = mapped_column(
        _enum(SourceStatus, "source_status"), default=SourceStatus.ACTIVE
    )


class Document(IdTimestampMixin, TenantMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("source_id", "external_id"),)

    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"))
    external_id: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(Text)
    # use_alter: циклическая FK documents ↔ document_versions
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_versions.id", use_alter=True, name="fk_documents_active_version")
    )
    status: Mapped[DocumentStatus] = mapped_column(
        _enum(DocumentStatus, "document_status"), default=DocumentStatus.ACTIVE
    )


class DocumentVersion(IdTimestampMixin, TenantMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "content_hash"),)

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    version: Mapped[int]
    content_hash: Mapped[str] = mapped_column(Text)
    source_updated_at: Mapped[datetime | None]
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[VersionStatus] = mapped_column(
        _enum(VersionStatus, "version_status"), default=VersionStatus.INDEXING
    )


class Chunk(IdTimestampMixin, TenantMixin, Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_version_id", "ordinal"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_chunks_metadata",
            "metadata",
            postgresql_using="gin",
            postgresql_ops={"metadata": "jsonb_path_ops"},
        ),
        Index("ix_chunks_collection_id", "collection_id"),
    )

    document_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_versions.id"))
    # Денормализация для фильтров поиска без JOIN (docs/data-model.md §2)
    collection_id: Mapped[uuid.UUID]
    ordinal: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIM))
    # Конфигурация russian: латинские токены обрабатываются english_stem (ADR-005)
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR, Computed("to_tsvector('russian', text)", persisted=True)
    )
    token_count: Mapped[int]
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)


class IngestJob(IdTimestampMixin, TenantMixin, Base):
    __tablename__ = "ingest_jobs"

    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id"))
    document_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_versions.id")
    )
    kind: Mapped[IngestJobKind] = mapped_column(_enum(IngestJobKind, "ingest_job_kind"))
    status: Mapped[IngestJobStatus] = mapped_column(
        _enum(IngestJobStatus, "ingest_job_status"), default=IngestJobStatus.QUEUED
    )
    steps: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    celery_task_id: Mapped[str | None] = mapped_column(Text)
