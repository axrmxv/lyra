"""Репозитории — единственная точка доступа к данным."""

from lyra.db.repositories.chat import ChatRepository
from lyra.db.repositories.chunks import ChunkRepository
from lyra.db.repositories.collections import CollectionRepository
from lyra.db.repositories.documents import DocumentRepository
from lyra.db.repositories.ingest_jobs import IngestJobRepository
from lyra.db.repositories.sources import SourceRepository
from lyra.db.repositories.users import UserRepository

__all__ = [
    "ChatRepository",
    "ChunkRepository",
    "CollectionRepository",
    "DocumentRepository",
    "IngestJobRepository",
    "SourceRepository",
    "UserRepository",
]
