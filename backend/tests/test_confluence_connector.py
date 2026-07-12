"""Тесты Confluence-коннектора c мок-API (respx): инкрементальность и удаления."""

import json
from typing import Any

import pytest
import respx
from httpx import Response

from lyra.ingest.connectors import ConfluenceConnector
from lyra.ingest.connectors.confluence import ConfluenceConfigError

BASE = "https://corp.example.com/wiki"


@pytest.fixture(autouse=True)
def token_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONFLUENCE_TOKEN", "test-token")


def config() -> dict[str, Any]:
    return {
        "base_url": BASE,
        "spaces": ["DEV"],
        "email": "bot@corp.ru",
        "token_secret_ref": "CONFLUENCE_TOKEN",
    }


def _page(page_id: str, title: str, when: str) -> dict[str, Any]:
    return {"id": page_id, "title": title, "version": {"when": when}}


def _mock_listing(pages: list[dict[str, Any]]) -> None:
    respx.get(f"{BASE}/rest/api/content").mock(
        return_value=Response(200, json={"results": pages, "size": len(pages)})
    )


def test_missing_token_is_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONFLUENCE_TOKEN", raising=False)
    with pytest.raises(ConfluenceConfigError):
        ConfluenceConnector(config())


def test_missing_spaces_is_config_error() -> None:
    with pytest.raises(ConfluenceConfigError):
        ConfluenceConnector({"base_url": BASE, "spaces": []})


@respx.mock
async def test_first_sync_returns_all_pages() -> None:
    _mock_listing(
        [
            _page("101", "Страница А", "2026-07-01T10:00:00.000Z"),
            _page("102", "Страница Б", "2026-07-02T10:00:00.000Z"),
        ]
    )
    changes = await ConfluenceConnector(config()).list_changes(None)
    assert {i.external_id for i in changes.added_or_updated} == {"101", "102"}
    assert changes.deleted_external_ids == []
    assert set(changes.next_cursor["known_ids"]) == {"101", "102"}


@respx.mock
async def test_incremental_sync_only_updated_and_deleted() -> None:
    # 101 не менялась, 102 удалена, 103 новая, 104 обновилась после last_sync
    _mock_listing(
        [
            _page("101", "А", "2026-07-01T10:00:00.000Z"),
            _page("103", "Новая", "2026-07-09T10:00:00.000Z"),
            _page("104", "Обновлённая", "2026-07-09T12:00:00.000Z"),
        ]
    )
    cursor = {
        "last_sync_at": "2026-07-05T00:00:00+00:00",
        "known_ids": ["101", "102", "104"],
    }
    changes = await ConfluenceConnector(config()).list_changes(cursor)
    changed_ids = {i.external_id for i in changes.added_or_updated}
    assert changed_ids == {"103", "104"}  # 101 без изменений — не попала
    assert changes.deleted_external_ids == ["102"]


@respx.mock
async def test_fetch_and_normalize() -> None:
    respx.get(f"{BASE}/rest/api/content/101").mock(
        return_value=Response(
            200,
            json={
                "id": "101",
                "title": "Регламент",
                "version": {"when": "2026-07-01T10:00:00.000Z"},
                "history": {"createdBy": {"displayName": "Иванов"}},
                "body": {"storage": {"value": "<h1>Регламент</h1><p>Текст процедуры.</p>"}},
            },
        )
    )
    connector = ConfluenceConnector(config())
    raw = await connector.fetch("101")
    assert raw.title == "Регламент" and raw.author == "Иванов"
    ir = connector.normalize(raw)
    assert ir.meta["url"] == f"{BASE}/pages/101"
    texts = [b.text for _, s in ir.iter_sections() for b in s.blocks]
    assert "Текст процедуры." in texts


@respx.mock
async def test_pagination() -> None:
    first = [_page(str(i), f"P{i}", "2026-07-01T10:00:00.000Z") for i in range(50)]
    second = [_page("999", "Последняя", "2026-07-01T10:00:00.000Z")]
    route = respx.get(f"{BASE}/rest/api/content")
    route.side_effect = [
        Response(200, json={"results": first, "size": 50}),
        Response(200, json={"results": second, "size": 1}),
    ]
    changes = await ConfluenceConnector(config()).list_changes(None)
    assert len(changes.added_or_updated) == 51
    # Второй запрос ушёл со смещением start=50
    assert json.loads(route.calls[1].request.url.params.get("start") or "0") == 50
