"""Retry-политика EmbeddingClient: backoff с jitter, без лишнего ожидания.

Сеть и sleep подменяются — тест детерминирован и мгновенен.
"""

import httpx
import pytest

from lyra.core.clients import embeddings as embeddings_module
from lyra.core.clients.embeddings import MAX_RETRIES, EmbeddingClient, EmbeddingError


@pytest.fixture()
def slept(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Перехват asyncio.sleep: длительности вместо реального ожидания."""
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(embeddings_module.asyncio, "sleep", fake_sleep)
    return delays


def _client(monkeypatch: pytest.MonkeyPatch, handler: httpx.MockTransport) -> EmbeddingClient:
    original = httpx.AsyncClient

    def build(**kwargs: object) -> httpx.AsyncClient:
        return original(transport=handler, timeout=kwargs.get("timeout"))  # type: ignore[arg-type]

    monkeypatch.setattr(embeddings_module.httpx, "AsyncClient", build)
    return EmbeddingClient("http://tei", batch_size=8)


async def test_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch, slept: list[float]) -> None:
    attempts = {"n": 0}

    def handle(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json=[[0.1, 0.2]])

    client = _client(monkeypatch, httpx.MockTransport(handle))
    assert await client.embed(["текст"]) == [[0.1, 0.2]]
    # Два падения — два ожидания; jitter держит их ниже полного backoff
    assert len(slept) == 2
    assert 0.5 <= slept[0] <= 1.0
    assert 1.0 <= slept[1] <= 2.0


async def test_no_sleep_after_last_attempt(
    monkeypatch: pytest.MonkeyPatch, slept: list[float]
) -> None:
    """Последняя неудача поднимает ошибку сразу, а не после ещё одной паузы."""
    client = _client(monkeypatch, httpx.MockTransport(lambda _r: httpx.Response(503)))
    with pytest.raises(EmbeddingError):
        await client.embed(["текст"])
    assert len(slept) == MAX_RETRIES - 1
