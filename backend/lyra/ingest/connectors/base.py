"""Контракт SourceConnector (ADR-010): list_changes / fetch / normalize.

Инкрементальность — через SyncCursor (хранится в sources.sync_cursor);
идемпотентность — content_hash в общем пайплайне, ключ (source_id, external_id).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from lyra.ingest.ir import DocumentIR

SyncCursor = dict[str, Any]


@dataclass
class ChangedItem:
    external_id: str
    title: str
    url: str | None
    updated_at: datetime | None


@dataclass
class ChangeSet:
    added_or_updated: list[ChangedItem] = field(default_factory=list)
    deleted_external_ids: list[str] = field(default_factory=list)
    next_cursor: SyncCursor = field(default_factory=dict)


@dataclass
class RawDocument:
    external_id: str
    title: str
    content: bytes
    fmt: str  # формат для parse_document
    url: str | None = None
    author: str | None = None
    updated_at: datetime | None = None


class SourceConnector(Protocol):
    async def list_changes(self, cursor: SyncCursor | None) -> ChangeSet: ...

    async def fetch(self, external_id: str) -> RawDocument: ...

    def normalize(self, raw: RawDocument) -> DocumentIR: ...
