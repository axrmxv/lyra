"""Модели данных — единая точка импорта (и регистрации в Base.metadata)."""

from lyra.db.base import Base
from lyra.db.models.chat import ChatSession, Feedback, Message, MessageCitation
from lyra.db.models.enums import (
    DocumentStatus,
    EvalItemKind,
    EvalRunStatus,
    FeedbackRating,
    IngestJobKind,
    IngestJobStatus,
    MessageRole,
    SessionRevokeReason,
    SourceStatus,
    SourceType,
    TenantStatus,
    UserRole,
    VersionStatus,
)
from lyra.db.models.evals import EvalDataset, EvalItem, EvalRecord, EvalRun
from lyra.db.models.identity import AuthSession, Tenant, User
from lyra.db.models.knowledge import (
    EMBEDDING_DIM,
    Chunk,
    Collection,
    Document,
    DocumentVersion,
    IngestJob,
    Source,
)

__all__ = [
    "EMBEDDING_DIM",
    "AuthSession",
    "Base",
    "ChatSession",
    "Chunk",
    "Collection",
    "Document",
    "DocumentStatus",
    "DocumentVersion",
    "EvalDataset",
    "EvalItem",
    "EvalItemKind",
    "EvalRecord",
    "EvalRun",
    "EvalRunStatus",
    "Feedback",
    "FeedbackRating",
    "IngestJob",
    "IngestJobKind",
    "IngestJobStatus",
    "Message",
    "MessageCitation",
    "MessageRole",
    "SessionRevokeReason",
    "Source",
    "SourceStatus",
    "SourceType",
    "Tenant",
    "TenantStatus",
    "User",
    "UserRole",
    "VersionStatus",
]
