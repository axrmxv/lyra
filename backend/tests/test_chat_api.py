"""Chat API (фаза 5): SSE-порядок событий, персистенция, владение сессией, 429.

Интеграционные: живой postgres (как test_rbac), граф — на FakeLLM/FakeRetriever
через override get_deps_factory; Redis не нужен (лимитер фейковый/fail-open).
"""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from lyra.api.app import create_app
from lyra.api.routes.chat import get_deps_factory
from lyra.core.auth import create_access_token, hash_password
from lyra.core.config import Settings, get_settings
from lyra.core.constants import DEFAULT_TENANT_ID
from lyra.db.models import (
    ChatSession,
    Chunk,
    Collection,
    Document,
    DocumentVersion,
    Feedback,
    Message,
    MessageCitation,
    Source,
    SourceType,
    User,
    UserRole,
    VersionStatus,
)
from lyra.db.repositories import UserRepository
from lyra.db.session import get_engine, get_sessionmaker
from lyra.rag.deps import GraphDeps
from lyra.rag.events import EventSink
from lyra.rag.state import SelfCheckResult, Sufficiency
from lyra.retrieval.interfaces import ScoredChunk
from tests.rag_fakes import FakeLLM, FakeRetriever, make_chunk

pytestmark = pytest.mark.integration

DOC_TITLE = "Политика отпусков"


def make_fake_factory(llm: FakeLLM, retriever: FakeRetriever) -> Any:
    def override() -> Any:
        def factory(sink: EventSink) -> GraphDeps:
            settings = Settings(_env_file=None)
            return GraphDeps(
                retriever=retriever,  # type: ignore[arg-type]
                llm=llm,
                settings=settings,
                sink=sink,
            )

        return factory

    return override


def happy_llm() -> FakeLLM:
    return FakeLLM(
        chat_responses={"generate": ["Отпуск составляет 28 дней [1]."]},
        structured_responses={
            "grade_sufficiency": [Sufficiency(sufficient=True, score=0.9)],
            "self_check": [SelfCheckResult(passed=True)],
        },
    )


@pytest.fixture()
async def corpus_chunks(migrated_db: Settings) -> AsyncIterator[list[ScoredChunk]]:
    """Реальные chunks в БД: message_citations.chunk_id — FK на chunks.id,
    случайные uuid из фейков нарушили бы его при персистенции цитат."""
    dsn = migrated_db.database_dsn.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(dsn)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    doc_url = "http://kb/vacation"
    async with maker() as session:
        collection = Collection(
            tenant_id=DEFAULT_TENANT_ID,
            name=f"chat-test-{uuid.uuid4().hex[:6]}",
            embedding_model="bge-m3",
        )
        session.add(collection)
        await session.flush()
        source = Source(
            tenant_id=DEFAULT_TENANT_ID,
            collection_id=collection.id,
            type=SourceType.UPLOAD,
            name="upload",
        )
        session.add(source)
        await session.flush()
        document = Document(
            tenant_id=DEFAULT_TENANT_ID,
            source_id=source.id,
            external_id=f"vacation-{uuid.uuid4().hex[:6]}",
            title=DOC_TITLE,
            url=doc_url,
        )
        session.add(document)
        await session.flush()
        version = DocumentVersion(
            tenant_id=DEFAULT_TENANT_ID,
            document_id=document.id,
            version=1,
            content_hash=uuid.uuid4().hex,
            status=VersionStatus.ACTIVE,
        )
        session.add(version)
        await session.flush()
        document.active_version_id = version.id
        chunks = [
            Chunk(
                tenant_id=DEFAULT_TENANT_ID,
                document_version_id=version.id,
                collection_id=collection.id,
                ordinal=i,
                text=f"Отпуск составляет 28 дней, пункт {i}.",
                token_count=50,
                embedding=[0.0] * 1024,
                meta={"doc_title": DOC_TITLE, "url": doc_url, "lang": "ru"},
            )
            for i in range(4)
        ]
        session.add_all(chunks)
        await session.commit()
        scored = [
            ScoredChunk(
                chunk_id=chunk.id,
                document_id=document.id,
                document_version_id=version.id,
                ordinal=chunk.ordinal,
                text=chunk.text,
                token_count=50,
                meta={"doc_title": DOC_TITLE, "url": doc_url, "lang": "ru"},
                rrf_score=0.03,
                rerank_score=0.3,
            )
            for chunk in chunks
        ]
    yield scored
    async with maker() as session:
        # chunk_id в citations — ON DELETE SET NULL, чистка безопасна
        await session.execute(
            update(Document).where(Document.id == document.id).values(active_version_id=None)
        )
        await session.execute(delete(Chunk).where(Chunk.document_version_id == version.id))
        await session.execute(delete(DocumentVersion).where(DocumentVersion.id == version.id))
        await session.execute(delete(Document).where(Document.id == document.id))
        await session.execute(delete(Source).where(Source.id == source.id))
        await session.execute(delete(Collection).where(Collection.id == collection.id))
        await session.commit()
    await engine.dispose()


@pytest.fixture()
async def app_client(migrated_db: Settings) -> AsyncIterator[AsyncClient]:
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.app = app  # type: ignore[attr-defined]
        yield client
    # Пул asyncpg привязан к loop теста — освобождаем до закрытия loop
    await get_engine().dispose()
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


@pytest.fixture()
async def two_users(migrated_db: Settings) -> AsyncIterator[tuple[User, User]]:
    """(владелец-viewer, второй viewer) — тесты владения сессией."""
    async for users in _make_users(migrated_db, [UserRole.VIEWER, UserRole.VIEWER]):
        yield users[0], users[1]


@pytest.fixture()
async def viewer_and_admin(migrated_db: Settings) -> AsyncIterator[tuple[User, User]]:
    async for users in _make_users(migrated_db, [UserRole.VIEWER, UserRole.ADMIN]):
        yield users[0], users[1]


async def _make_users(migrated_db: Settings, roles: list[UserRole]) -> AsyncIterator[list[User]]:
    dsn = migrated_db.database_dsn.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(dsn)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    created: list[User] = []
    async with maker() as session:
        repo = UserRepository(session)
        for i, role in enumerate(roles):
            created.append(
                await repo.create(
                    DEFAULT_TENANT_ID,
                    email=f"chat-{i}-{uuid.uuid4().hex[:6]}@lyra.local",
                    password_hash=hash_password("password1"),
                    role=role,
                )
            )
        await session.commit()
    yield created
    # Данные создаются через API с commit — чистим зависимости в порядке FK
    async with maker() as session:
        user_ids = [user.id for user in created]
        session_ids = select(ChatSession.id).where(ChatSession.user_id.in_(user_ids))
        message_ids = select(Message.id).where(Message.session_id.in_(session_ids))
        await session.execute(
            delete(MessageCitation).where(MessageCitation.message_id.in_(message_ids))
        )
        await session.execute(delete(Feedback).where(Feedback.user_id.in_(user_ids)))
        await session.execute(delete(Message).where(Message.session_id.in_(session_ids)))
        await session.execute(delete(ChatSession).where(ChatSession.user_id.in_(user_ids)))
        await session.execute(delete(User).where(User.id.in_(user_ids)))
        await session.commit()
    await engine.dispose()


def auth(user: User) -> dict[str, str]:
    token, _ = create_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        secret=Settings(_env_file=None).jwt_secret,
    )
    return {"Authorization": f"Bearer {token}"}


def parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in text.strip().split("\n\n"):
        event_name, data = None, None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data = json.loads(line.removeprefix("data: "))
        assert event_name is not None and data is not None, block
        events.append((event_name, data))
    return events


async def create_session_id(client: AsyncClient, user: User) -> str:
    response = await client.post("/api/v1/chat/sessions", headers=auth(user))
    assert response.status_code == 201, response.text
    return str(response.json()["session_id"])


async def send_message(
    client: AsyncClient, user: User, session_id: str, content: str = "Сколько дней отпуска?"
) -> list[tuple[str, dict[str, Any]]]:
    response = await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        headers=auth(user),
        json={"content": content},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse_sse(response.text)


async def test_sse_event_order_and_final(
    app_client: AsyncClient, two_users: tuple[User, User], corpus_chunks: list[ScoredChunk]
) -> None:
    user, _ = two_users
    app = app_client.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_deps_factory] = make_fake_factory(
        happy_llm(), FakeRetriever([corpus_chunks])
    )
    session_id = await create_session_id(app_client, user)
    events = await send_message(app_client, user, session_id)

    kinds = [kind for kind, _ in events]
    # status* → token* → final; статусы по стадиям контракта
    assert kinds[-1] == "final"
    statuses = [data["stage"] for kind, data in events if kind == "status"]
    assert statuses == ["retrieving", "grading", "generating", "self_check"]
    first_token = kinds.index("token")
    assert all(k in ("status", "token") for k in kinds[:-1])
    assert kinds[first_token - 1] == "status"  # токены после статуса generating

    final = events[-1][1]
    assert final["refusal"] is False
    assert "[1]" in final["answer"]
    assert final["citations"][0]["id"] == 1
    assert final["citations"][0]["document_title"] == DOC_TITLE
    assert final["confidence"]["label"] in ("high", "medium")
    assert final["trace_id"]
    assert final["usage"]["llm_calls"] >= 3
    assert uuid.UUID(final["message_id"])
    app.dependency_overrides.clear()


async def test_messages_persisted_with_citations(
    app_client: AsyncClient, two_users: tuple[User, User], corpus_chunks: list[ScoredChunk]
) -> None:
    user, _ = two_users
    app = app_client.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_deps_factory] = make_fake_factory(
        happy_llm(), FakeRetriever([corpus_chunks])
    )
    session_id = await create_session_id(app_client, user)
    events = await send_message(app_client, user, session_id)
    final = events[-1][1]

    response = await app_client.get(
        f"/api/v1/chat/sessions/{session_id}/messages", headers=auth(user)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    roles = [item["role"] for item in body["items"]]
    assert roles == ["user", "assistant"]
    assistant = body["items"][1]
    assert assistant["id"] == final["message_id"]
    assert assistant["content"] == final["answer"]
    assert assistant["confidence"]["label"] == final["confidence"]["label"]
    assert len(assistant["citations"]) == len(final["citations"])
    assert assistant["citations"][0]["quote"] == final["citations"][0]["quote"]

    # Сессия получила заголовок из первого сообщения
    sessions = await app_client.get("/api/v1/chat/sessions", headers=auth(user))
    titles = [item["title"] for item in sessions.json()["items"] if item["id"] == session_id]
    assert titles == ["Сколько дней отпуска?"]
    app.dependency_overrides.clear()


async def test_foreign_session_forbidden(
    app_client: AsyncClient, two_users: tuple[User, User]
) -> None:
    owner, intruder = two_users
    session_id = await create_session_id(app_client, owner)

    response = await app_client.get(
        f"/api/v1/chat/sessions/{session_id}/messages", headers=auth(intruder)
    )
    assert response.status_code == 403

    response = await app_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        headers=auth(intruder),
        json={"content": "чужая сессия"},
    )
    assert response.status_code == 403

    missing = await app_client.get(
        f"/api/v1/chat/sessions/{uuid.uuid4()}/messages", headers=auth(owner)
    )
    assert missing.status_code == 404


async def test_refusal_final_payload(app_client: AsyncClient, two_users: tuple[User, User]) -> None:
    user, _ = two_users
    weak = [make_chunk("нерелевантно", title="Другой документ")]
    llm = FakeLLM(chat_responses={"corrective_retrieve": ["v2", "v3"]})
    app = app_client.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_deps_factory] = make_fake_factory(
        llm, FakeRetriever([weak, weak, weak])
    )
    session_id = await create_session_id(app_client, user)
    events = await send_message(app_client, user, session_id, content="Вопрос вне корпуса?")
    final = events[-1][1]
    assert final["refusal"] is True
    assert final["citations"] == []
    assert final["confidence"]["label"] == "low"
    assert final["nearest_documents"]
    assert final["nearest_documents"][0]["title"] == "Другой документ"
    app.dependency_overrides.clear()


async def test_llm_unavailable_error_event(
    app_client: AsyncClient, two_users: tuple[User, User]
) -> None:
    from lyra.core.clients.llm import LLMUnavailable

    class BrokenLLM(FakeLLM):
        async def structured(self, *args: Any, **kwargs: Any) -> Any:
            raise LLMUnavailable("connection refused")

    user, _ = two_users
    app = app_client.app  # type: ignore[attr-defined]
    # 4 кандидата с rerank выше порога: эвристики grade пропускают до
    # LLM-judge (structured) — там и падает BrokenLLM
    broken_chunks = [make_chunk(f"Отпуск 28 дней, пункт {i}.", rerank=0.3) for i in range(4)]
    app.dependency_overrides[get_deps_factory] = make_fake_factory(
        BrokenLLM(), FakeRetriever([broken_chunks])
    )
    session_id = await create_session_id(app_client, user)
    response = await app_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        headers=auth(user),
        json={"content": "вопрос"},
    )
    assert response.status_code == 200  # стрим уже начался — ошибка событием
    events = parse_sse(response.text)
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "llm_unavailable"
    assert all(kind != "final" for kind, _ in events)


async def test_chat_rate_limit_429(app_client: AsyncClient, two_users: tuple[User, User]) -> None:
    import lyra.api.deps as api_deps
    from lyra.core.ratelimit import RateDecision

    class DenyLimiter:
        async def hit(self, key: str, limit: int, window_s: int = 60) -> RateDecision:
            return RateDecision(allowed=False, retry_after_s=42)

    user, _ = two_users
    session_id = await create_session_id(app_client, user)

    original = api_deps.get_rate_limiter
    api_deps.get_rate_limiter = DenyLimiter  # type: ignore[assignment]
    try:
        response = await app_client.post(
            f"/api/v1/chat/sessions/{session_id}/messages",
            headers=auth(user),
            json={"content": "вопрос"},
        )
    finally:
        api_deps.get_rate_limiter = original
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "42"
    assert response.json()["error"]["code"] == "rate_limited"


async def test_feedback_flow_uc7(
    app_client: AsyncClient,
    viewer_and_admin: tuple[User, User],
    corpus_chunks: list[ScoredChunk],
) -> None:
    """UC-7: 👎 с комментарием сохраняется, admin видит в GET /feedback."""
    viewer, admin = viewer_and_admin
    app = app_client.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_deps_factory] = make_fake_factory(
        happy_llm(), FakeRetriever([corpus_chunks])
    )
    session_id = await create_session_id(app_client, viewer)
    events = await send_message(app_client, viewer, session_id)
    message_id = events[-1][1]["message_id"]
    app.dependency_overrides.clear()

    response = await app_client.post(
        "/api/v1/feedback",
        headers=auth(viewer),
        json={"message_id": message_id, "rating": "down", "comment": "ответ неточный"},
    )
    assert response.status_code == 201, response.text
    feedback_id = response.json()["id"]

    listing = await app_client.get(
        "/api/v1/feedback", headers=auth(admin), params={"rating": "down"}
    )
    assert listing.status_code == 200
    body = listing.json()
    ours = [item for item in body["items"] if item["id"] == feedback_id]
    assert ours and ours[0]["comment"] == "ответ неточный"
    assert ours[0]["message_id"] == message_id
    assert body["total"] >= 1

    # Фидбек на чужое сообщение запрещён
    foreign = await app_client.post(
        "/api/v1/feedback",
        headers=auth(admin),
        json={"message_id": message_id, "rating": "up"},
    )
    assert foreign.status_code == 403

    # Несуществующее сообщение → 404
    missing = await app_client.post(
        "/api/v1/feedback",
        headers=auth(viewer),
        json={"message_id": str(uuid.uuid4()), "rating": "up"},
    )
    assert missing.status_code == 404


async def test_generation_gate_overflow_429(
    app_client: AsyncClient, two_users: tuple[User, User]
) -> None:
    from lyra.core.concurrency import get_generation_gate

    user, _ = two_users
    session_id = await create_session_id(app_client, user)
    gate = get_generation_gate()
    # Занимаем все слоты — следующий запрос должен получить 429
    limit = get_settings().llm_max_concurrency
    for _i in range(limit):
        assert await gate.try_acquire()
    try:
        response = await app_client.post(
            f"/api/v1/chat/sessions/{session_id}/messages",
            headers=auth(user),
            json={"content": "вопрос"},
        )
        assert response.status_code == 429
        assert response.json()["error"]["code"] == "overloaded"
        assert "Retry-After" in response.headers
    finally:
        for _i in range(limit):
            gate.release()
