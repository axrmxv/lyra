"""MCP-сервер поверх Confluence-коннектора (ADR-010).

Тонкая обёртка над теми же методами: демонстрирует MCP-подход в MVP;
в production-треке P4 этими tools пользуется агентный поиск.

Запуск (stdio): python -m lyra.ingest.connectors.confluence_mcp
Конфигурация — env: CONFLUENCE_BASE_URL, CONFLUENCE_EMAIL, CONFLUENCE_TOKEN.
"""

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from lyra.ingest.connectors.confluence import ConfluenceConnector

mcp = FastMCP("lyra-confluence")


def _connector() -> ConfluenceConnector:
    return ConfluenceConnector(
        {
            "base_url": os.environ.get("CONFLUENCE_BASE_URL", ""),
            "spaces": os.environ.get("CONFLUENCE_SPACES", "").split(",") or ["-"],
            "email": os.environ.get("CONFLUENCE_EMAIL", ""),
            "token_secret_ref": "CONFLUENCE_TOKEN",
        }
    )


@mcp.tool()
async def list_spaces() -> list[dict[str, str]]:
    """Список spaces Confluence-инстанса."""
    connector = _connector()
    async with httpx.AsyncClient(timeout=30.0) as client:
        data = await connector._get(client, "/rest/api/space", limit=50)
    return [{"key": s.get("key", ""), "name": s.get("name", "")} for s in data.get("results", [])]


@mcp.tool()
async def search_pages(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Поиск страниц по тексту (CQL siteSearch)."""
    connector = _connector()
    async with httpx.AsyncClient(timeout=30.0) as client:
        data = await connector._get(
            client,
            "/rest/api/content/search",
            cql=f'siteSearch ~ "{query}" and type = page',
            limit=limit,
        )
    return [{"id": item.get("id"), "title": item.get("title")} for item in data.get("results", [])]


@mcp.tool()
async def get_page(page_id: str) -> dict[str, Any]:
    """Содержимое страницы (плоский текст из storage-XHTML)."""
    connector = _connector()
    raw = await connector.fetch(page_id)
    ir = connector.normalize(raw)
    text = "\n\n".join(block.text for _, section in ir.iter_sections() for block in section.blocks)
    return {"id": page_id, "title": raw.title, "url": raw.url, "text": text}


if __name__ == "__main__":
    mcp.run()
