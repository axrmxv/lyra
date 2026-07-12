"""Коннекторы источников — контракт ADR-010."""

from lyra.ingest.connectors.base import ChangeSet, RawDocument, SourceConnector, SyncCursor
from lyra.ingest.connectors.confluence import ConfluenceConnector

__all__ = ["ChangeSet", "ConfluenceConnector", "RawDocument", "SourceConnector", "SyncCursor"]
