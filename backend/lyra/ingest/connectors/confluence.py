"""Confluence Cloud коннектор (ADR-010).

- list_changes: CQL lastModified >= cursor по выбранным spaces + пагинация;
  удаления — diff полного списка id против known_ids из курсора.
- fetch: body.storage (XHTML) + метаданные.
- Токен: env-переменная, имя которой лежит в config.token_secret_ref;
  значение в БД не хранится (docs/security-and-access.md §5).
- Auth Confluence Cloud: Basic (email + API-токен).
"""

import base64
import os
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from lyra.ingest.connectors.base import ChangedItem, ChangeSet, RawDocument, SyncCursor
from lyra.ingest.ir import DocumentIR
from lyra.ingest.parsers.confluence_html import parse_confluence_html

logger = structlog.get_logger(__name__)

PAGE_LIMIT = 50
TIMEOUT_S = 30.0


class ConfluenceConfigError(Exception):
    """Невалидная конфигурация источника — permanent."""


class ConfluenceConnector:
    def __init__(self, config: dict[str, Any]) -> None:
        self._base_url = str(config.get("base_url", "")).rstrip("/")
        self._spaces: list[str] = list(config.get("spaces", []))
        if not self._base_url or not self._spaces:
            raise ConfluenceConfigError("В config источника обязательны base_url и spaces")
        token_ref = str(config.get("token_secret_ref", "CONFLUENCE_TOKEN"))
        token = os.environ.get(token_ref, "")
        email = str(config.get("email", ""))
        if not token:
            raise ConfluenceConfigError(f"Env-переменная {token_ref} не задана")
        credentials = base64.b64encode(f"{email}:{token}".encode()).decode()
        self._headers = {"Authorization": f"Basic {credentials}"}

    async def _get(self, client: httpx.AsyncClient, path: str, **params: Any) -> dict[str, Any]:
        response = await client.get(f"{self._base_url}{path}", params=params, headers=self._headers)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data

    async def _list_page_ids(self, client: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
        """Все страницы выбранных spaces: external_id → {title, updated_at}."""
        pages: dict[str, dict[str, Any]] = {}
        for space in self._spaces:
            start = 0
            while True:
                data = await self._get(
                    client,
                    "/rest/api/content",
                    spaceKey=space,
                    type="page",
                    status="current",
                    limit=PAGE_LIMIT,
                    start=start,
                    expand="version",
                )
                for item in data.get("results", []):
                    pages[str(item["id"])] = {
                        "title": item.get("title", ""),
                        "updated_at": item.get("version", {}).get("when"),
                    }
                if data.get("size", 0) < PAGE_LIMIT:
                    break
                start += PAGE_LIMIT
        return pages

    async def list_changes(self, cursor: SyncCursor | None) -> ChangeSet:
        cursor = cursor or {}
        last_sync = cursor.get("last_sync_at")
        known_ids: set[str] = set(cursor.get("known_ids", []))

        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            pages = await self._list_page_ids(client)

        changed: list[ChangedItem] = []
        for external_id, info in pages.items():
            updated_raw = info.get("updated_at")
            updated_at = (
                datetime.fromisoformat(updated_raw.replace("Z", "+00:00")) if updated_raw else None
            )
            is_new = external_id not in known_ids
            is_updated = (
                last_sync is not None
                and updated_at is not None
                and updated_at > datetime.fromisoformat(last_sync)
            )
            if is_new or is_updated or last_sync is None:
                changed.append(
                    ChangedItem(
                        external_id=external_id,
                        title=info.get("title", external_id),
                        url=f"{self._base_url}/pages/{external_id}",
                        updated_at=updated_at,
                    )
                )

        deleted = sorted(known_ids - set(pages))
        next_cursor: SyncCursor = {
            "last_sync_at": datetime.now(UTC).isoformat(),
            "known_ids": sorted(pages),
        }
        logger.info(
            "confluence_changes",
            changed=len(changed),
            deleted=len(deleted),
            total_pages=len(pages),
        )
        return ChangeSet(
            added_or_updated=changed, deleted_external_ids=deleted, next_cursor=next_cursor
        )

    async def fetch(self, external_id: str) -> RawDocument:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            data = await self._get(
                client,
                f"/rest/api/content/{external_id}",
                expand="body.storage,version,history.createdBy",
            )
        html = data.get("body", {}).get("storage", {}).get("value", "")
        updated_raw = data.get("version", {}).get("when")
        return RawDocument(
            external_id=external_id,
            title=data.get("title", external_id),
            content=html.encode("utf-8"),
            fmt="confluence",
            url=f"{self._base_url}/pages/{external_id}",
            author=data.get("history", {}).get("createdBy", {}).get("displayName"),
            updated_at=(
                datetime.fromisoformat(updated_raw.replace("Z", "+00:00")) if updated_raw else None
            ),
        )

    def normalize(self, raw: RawDocument) -> DocumentIR:
        ir = parse_confluence_html(raw.content.decode("utf-8"), title=raw.title)
        ir.meta["url"] = raw.url
        return ir
