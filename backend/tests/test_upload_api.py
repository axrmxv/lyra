"""Тесты POST /documents/upload: 202 + job + файл + постановка задачи (FR-2).

Пайплайн не выполняется (delay замокан) — он покрыт test_ingest_service;
здесь — синхронная часть API: валидация, неявный upload-source, персистенция.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import lyra.workers.tasks.ingest as ingest_tasks
from lyra.api.app import create_app
from lyra.core.auth import create_access_token, hash_password
from lyra.core.config import Settings, get_settings
from lyra.core.constants import DEFAULT_TENANT_ID
from lyra.db.models import SourceType, UserRole
from lyra.db.repositories import CollectionRepository, SourceRepository, UserRepository
from lyra.db.session import get_engine, get_sessionmaker

pytestmark = pytest.mark.integration


@pytest.fixture()
def dispatched(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []

    class FakeResult:
        id = "fake-task-id"

    def fake_delay(*args: str, **kwargs: str) -> FakeResult:
        calls.append(args)
        return FakeResult()

    monkeypatch.setattr(ingest_tasks.process_upload, "delay", fake_delay)
    return calls


@pytest.fixture()
async def env(
    migrated_db: Settings,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, object]]:
    """app-клиент + editor-токен + коллекция; upload_dir → tmp."""
    monkeypatch.setenv("LYRA_UPLOAD_DIR", str(tmp_path_factory.mktemp("uploads")))
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()

    dsn = migrated_db.database_dsn.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(dsn)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        user = await UserRepository(session).create(
            DEFAULT_TENANT_ID,
            email=f"up-{uuid.uuid4().hex[:6]}@lyra.local",
            password_hash=hash_password("password1"),
            role=UserRole.EDITOR,
        )
        collection = await CollectionRepository(session).create(
            DEFAULT_TENANT_ID, name=f"c-{uuid.uuid4().hex[:6]}", embedding_model="BAAI/bge-m3"
        )
        await session.commit()
        collection_id, user_id, user_tenant, user_role = (
            collection.id,
            user.id,
            user.tenant_id,
            user.role,
        )
    token, _ = create_access_token(
        user_id=user_id,
        tenant_id=user_tenant,
        role=user_role,
        secret=Settings(_env_file=None).jwt_secret,
    )
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield {
            "client": client,
            "headers": {"Authorization": f"Bearer {token}"},
            "collection_id": collection_id,
            "maker": maker,
        }
    await engine.dispose()
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


async def test_upload_accepted_and_dispatched(
    env: dict[str, object], dispatched: list[tuple[str, ...]]
) -> None:
    client: AsyncClient = env["client"]  # type: ignore[assignment]
    response = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("политика.md", "# Отпуск\n\n28 дней.".encode(), "text/markdown")},
        data={"collection_id": str(env["collection_id"])},
        headers=env["headers"],  # type: ignore[arg-type]
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "queued"
    assert len(dispatched) == 1
    job_id, document_id, file_path, filename, fmt = dispatched[0]
    assert body["job_id"] == job_id and body["document_id"] == document_id
    assert filename == "политика.md" and fmt == "markdown"
    with open(file_path, "rb") as fh:
        assert fh.read().startswith("# Отпуск".encode())

    # Неявный upload-source создан для коллекции
    maker = env["maker"]
    async with maker() as session:  # type: ignore[union-attr]
        source = await SourceRepository(session).get_upload_source(
            DEFAULT_TENANT_ID,
            env["collection_id"],  # type: ignore[arg-type]
        )
        assert source is not None and source.type == SourceType.UPLOAD


async def test_upload_too_large_413(
    env: dict[str, object],
    dispatched: list[tuple[str, ...]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LYRA_UPLOAD_MAX_BYTES", "10")
    get_settings.cache_clear()
    client: AsyncClient = env["client"]  # type: ignore[assignment]
    response = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("big.txt", b"x" * 100, "text/plain")},
        data={"collection_id": str(env["collection_id"])},
        headers=env["headers"],  # type: ignore[arg-type]
    )
    assert response.status_code == 413
    assert dispatched == []


async def test_upload_unsupported_type_415(
    env: dict[str, object], dispatched: list[tuple[str, ...]]
) -> None:
    client: AsyncClient = env["client"]  # type: ignore[assignment]
    response = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("virus.zip", b"PK\x03\x04payload", "application/zip")},
        data={"collection_id": str(env["collection_id"])},
        headers=env["headers"],  # type: ignore[arg-type]
    )
    assert response.status_code == 415
    assert dispatched == []


async def test_upload_requires_editor(env: dict[str, object]) -> None:
    client: AsyncClient = env["client"]  # type: ignore[assignment]
    response = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("a.txt", b"text", "text/plain")},
        data={"collection_id": str(env["collection_id"])},
    )
    assert response.status_code == 401
