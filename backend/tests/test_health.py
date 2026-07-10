"""Тесты /health и /health/ready: статусы зависимостей и деградация."""

import pytest
from fastapi.testclient import TestClient

from lyra.api import readiness
from lyra.api.app import create_app
from lyra.core.config import Settings


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


async def _up(_settings: Settings) -> None:
    return None


async def _down(_settings: Settings) -> None:
    raise ConnectionError("dependency unavailable")


def test_health_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Trace-Id"].startswith("tr_")


def test_ready_all_up(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readiness, "CHECKS", dict.fromkeys(readiness.CHECKS, _up))
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert set(body["dependencies"]) == {"postgres", "redis", "ollama", "embeddings", "reranker"}
    assert all(status == "up" for status in body["dependencies"].values())


def test_ready_reports_down_dependency(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    checks = dict.fromkeys(readiness.CHECKS, _up)
    checks["redis"] = _down
    monkeypatch.setattr(readiness, "CHECKS", checks)
    response = client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["dependencies"]["redis"] == "down"
    assert body["dependencies"]["postgres"] == "up"


def test_metrics_exposed(client: TestClient) -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "python_info" in response.text
