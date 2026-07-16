"""RBAC-матрица docs/security-and-access.md §2 — параметризованный тест.

Каждый эндпоинт × каждая роль: ниже минимальной → 403, без токена → 401.
Негативные сценарии логина (неверный пароль, деактивированный пользователь) —
здесь же, через живой API.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from lyra.api.app import create_app
from lyra.core.auth import create_access_token, hash_password
from lyra.core.config import Settings, get_settings
from lyra.core.constants import DEFAULT_TENANT_ID
from lyra.db.models import ChatSession, User, UserRole
from lyra.db.repositories import UserRepository
from lyra.db.session import get_engine, get_sessionmaker

pytestmark = pytest.mark.integration

# Эндпоинт → (method, path, минимальная роль, payload)
RBAC_MATRIX = [
    ("GET", "/api/v1/auth/me", UserRole.VIEWER, None),
    ("GET", "/api/v1/admin/users", UserRole.ADMIN, None),
    ("POST", "/api/v1/admin/users", UserRole.ADMIN, {"email": "x@l.ru", "password": "password1"}),
    ("PATCH", f"/api/v1/admin/users/{uuid.uuid4()}", UserRole.ADMIN, {"is_active": True}),
    ("GET", "/api/v1/admin/collections", UserRole.ADMIN, None),
    ("POST", "/api/v1/admin/collections", UserRole.ADMIN, {"name": "c"}),
    ("PATCH", f"/api/v1/admin/collections/{uuid.uuid4()}", UserRole.ADMIN, {"name": "c2"}),
    # Фаза 2: ingest-эндпоинты (docs/api-contract.md §2, §6)
    ("GET", "/api/v1/documents", UserRole.VIEWER, None),
    ("GET", f"/api/v1/documents/{uuid.uuid4()}", UserRole.VIEWER, None),
    ("DELETE", f"/api/v1/documents/{uuid.uuid4()}", UserRole.EDITOR, None),
    ("GET", "/api/v1/sources", UserRole.VIEWER, None),
    ("GET", f"/api/v1/sources/{uuid.uuid4()}", UserRole.VIEWER, None),
    ("PATCH", f"/api/v1/sources/{uuid.uuid4()}", UserRole.EDITOR, {"name": "s"}),
    ("DELETE", f"/api/v1/sources/{uuid.uuid4()}", UserRole.EDITOR, None),
    ("POST", f"/api/v1/sources/{uuid.uuid4()}/sync", UserRole.EDITOR, None),
    ("GET", "/api/v1/ingest/jobs", UserRole.EDITOR, None),
    ("GET", f"/api/v1/ingest/jobs/{uuid.uuid4()}", UserRole.EDITOR, None),
    ("POST", "/api/v1/admin/reindex", UserRole.ADMIN, {"collection_id": str(uuid.uuid4())}),
    # Фаза 3: retrieval (docs/api-contract.md §3)
    ("POST", "/api/v1/search", UserRole.VIEWER, {"query": "тест", "rerank": False}),
    # Фаза 5: chat и feedback (docs/api-contract.md §4-5)
    ("POST", "/api/v1/chat/sessions", UserRole.VIEWER, None),
    ("GET", "/api/v1/chat/sessions", UserRole.VIEWER, None),
    ("GET", f"/api/v1/chat/sessions/{uuid.uuid4()}/messages", UserRole.VIEWER, None),
    ("POST", f"/api/v1/chat/sessions/{uuid.uuid4()}/messages", UserRole.VIEWER, {"content": "т"}),
    (
        "POST",
        "/api/v1/feedback",
        UserRole.VIEWER,
        {"message_id": str(uuid.uuid4()), "rating": "up"},
    ),
    ("GET", "/api/v1/feedback", UserRole.ADMIN, None),
    # Фаза 6: eval-runs (docs/api-contract.md §6, UC-8)
    ("POST", "/api/v1/admin/eval-runs", UserRole.ADMIN, {"dataset_name": "golden"}),
    ("GET", f"/api/v1/admin/eval-runs/{uuid.uuid4()}", UserRole.ADMIN, None),
]

ROLES = [UserRole.VIEWER, UserRole.EDITOR, UserRole.ADMIN]


@pytest.fixture(autouse=True)
def no_celery_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Роуты ставят Celery-задачи; в тестах брокер недоступен — глушим delay."""
    import lyra.workers.tasks.evals as evals_tasks
    import lyra.workers.tasks.ingest as ingest_tasks

    class FakeResult:
        id = "fake-task-id"

    for task_name in ("process_upload", "sync_source", "reindex_collection"):
        task = getattr(ingest_tasks, task_name)
        monkeypatch.setattr(task, "delay", lambda *a, **k: FakeResult())
    monkeypatch.setattr(evals_tasks.run_evals_task, "delay", lambda *a, **k: FakeResult())


@pytest.fixture(autouse=True)
def fast_search(monkeypatch: pytest.MonkeyPatch) -> None:
    """RBAC-тесты /search не ходят в TEI: фейковый эмбеддер (пустая выдача — 200)."""

    class FakeEmbeddings:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def embed_one(self, text: str) -> list[float]:
            return [0.0] * 1024

        async def embed(self, texts: list[str]) -> list[list[float]]:
            return [[0.0] * 1024 for _ in texts]

    monkeypatch.setattr("lyra.retrieval.retriever.EmbeddingClient", FakeEmbeddings)


@pytest.fixture()
async def client(migrated_db: Settings) -> AsyncIterator[AsyncClient]:
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


@pytest.fixture()
async def users_by_role(migrated_db: Settings) -> AsyncIterator[dict[UserRole, User]]:
    """Пользователь каждой роли; создаются напрямую в БД, чистятся после."""
    dsn = migrated_db.database_dsn.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(dsn)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    created: dict[UserRole, User] = {}
    async with maker() as session:
        repo = UserRepository(session)
        for role in ROLES:
            created[role] = await repo.create(
                DEFAULT_TENANT_ID,
                email=f"rbac-{role.value}-{uuid.uuid4().hex[:6]}@lyra.local",
                password_hash=hash_password("password1"),
                role=role,
            )
        await session.commit()
    yield created
    async with maker() as session:
        user_ids = [user.id for user in created.values()]
        # POST /chat/sessions в матрице создаёт сессии — чистим до users (FK)
        await session.execute(delete(ChatSession).where(ChatSession.user_id.in_(user_ids)))
        await session.execute(delete(User).where(User.id.in_(user_ids)))
        await session.commit()
    await engine.dispose()


def _token_for(user: User) -> str:
    token, _ = create_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        secret=Settings(_env_file=None).jwt_secret,
    )
    return token


@pytest.mark.parametrize(("method", "path", "min_role", "payload"), RBAC_MATRIX)
async def test_endpoint_requires_auth(
    client: AsyncClient,
    method: str,
    path: str,
    min_role: UserRole,
    payload: dict[str, object] | None,
) -> None:
    response = await client.request(method, path, json=payload)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize(("method", "path", "min_role", "payload"), RBAC_MATRIX)
@pytest.mark.parametrize("role", ROLES)
async def test_rbac_matrix(
    client: AsyncClient,
    users_by_role: dict[UserRole, User],
    method: str,
    path: str,
    min_role: UserRole,
    payload: dict[str, object] | None,
    role: UserRole,
) -> None:
    headers = {"Authorization": f"Bearer {_token_for(users_by_role[role])}"}
    response = await client.request(method, path, json=payload, headers=headers)
    allowed = {UserRole.VIEWER: 0, UserRole.EDITOR: 1, UserRole.ADMIN: 2}
    if allowed[role] >= allowed[min_role]:
        # Роль достаточна: не 401/403 (404/409 допустимы — случайные id в path)
        assert response.status_code not in (401, 403), response.text
    else:
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden"


async def test_login_flow(client: AsyncClient, users_by_role: dict[UserRole, User]) -> None:
    user = users_by_role[UserRole.VIEWER]
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "password1"}
    )
    assert response.status_code == 200
    body = response.json()
    token = body["access_token"]
    assert body["user"]["role"] == "viewer"

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == user.email


async def test_login_wrong_password(
    client: AsyncClient, users_by_role: dict[UserRole, User]
) -> None:
    user = users_by_role[UserRole.VIEWER]
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "wrong-password"}
    )
    assert response.status_code == 401


async def test_inactive_user_rejected(
    client: AsyncClient, users_by_role: dict[UserRole, User], migrated_db: Settings
) -> None:
    user = users_by_role[UserRole.EDITOR]
    dsn = migrated_db.database_dsn.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(dsn)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        await UserRepository(session).update(DEFAULT_TENANT_ID, user.id, is_active=False)
        await session.commit()
    await engine.dispose()

    token = _token_for(user)
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
