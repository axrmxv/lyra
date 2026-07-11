"""Перечисления доменной модели — значения строго по docs/data-model.md §2."""

from enum import StrEnum


class TenantStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class UserRole(StrEnum):
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


class SourceType(StrEnum):
    UPLOAD = "upload"
    CONFLUENCE = "confluence"
    NOTION = "notion"  # задел production-трека P2
    GDRIVE = "gdrive"  # задел production-трека P2


class SourceStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"


class DocumentStatus(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"


class VersionStatus(StrEnum):
    INDEXING = "indexing"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    FAILED = "failed"


class IngestJobKind(StrEnum):
    UPLOAD = "upload"
    SYNC = "sync"
    REINDEX = "reindex"


class IngestJobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    FAILED_PII = "failed_pii"
    SKIPPED_DUPLICATE = "skipped_duplicate"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class FeedbackRating(StrEnum):
    UP = "up"
    DOWN = "down"


class EvalItemKind(StrEnum):
    ANSWERABLE = "answerable"
    UNANSWERABLE = "unanswerable"
    PARAPHRASE = "paraphrase"


class EvalRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
