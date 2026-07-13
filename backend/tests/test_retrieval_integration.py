"""Интеграционные тесты retrieval: каналы на реальном pgvector/tsvector,
retriever c фейковыми клиентами, graceful degradation (respx).

Векторы фикстур — синтетические (базисные направления в 1024-мерном
пространстве): точный контроль cosine-близости без модели.
"""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import respx
from httpx import Response
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from lyra.core.config import Settings
from lyra.db.models import (
    Chunk,
    Collection,
    Document,
    DocumentVersion,
    Source,
    SourceType,
)
from lyra.db.repositories import (
    ChunkRepository,
    CollectionRepository,
    DocumentRepository,
    SourceRepository,
)
from lyra.retrieval import cache as cache_module
from lyra.retrieval.cache import RetrievalCache
from lyra.retrieval.channels import Bm25Store, PgVectorStore
from lyra.retrieval.interfaces import AccessContext, ScoredChunk, SearchFilters
from lyra.retrieval.retriever import HybridRetriever

pytestmark = pytest.mark.integration

DIM = 1024


def unit_vector(direction: int, weight: float = 1.0) -> list[float]:
    vector = [0.0] * DIM
    vector[direction] = weight
    return vector


class FakeEmbeddings:
    """Запрос 'вектор-0' → базис 0, 'вектор-1' → базис 1 и т.д."""

    async def embed_one(self, text: str) -> list[float]:
        direction = 0
        for token in text.split():
            if token.startswith("вектор-"):
                direction = int(token.split("-")[1])
        return unit_vector(direction)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed_one(t) for t in texts]


class NullCache:
    async def get_embedding(self, query: str) -> None:
        return None

    async def set_embedding(self, query: str, vector: list[float]) -> None:
        return None

    async def get_result(self, key: str) -> None:
        return None

    async def set_result(self, key: str, chunks: list[Any]) -> None:
        return None


async def seed_corpus(session: AsyncSession, tenant_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """Три документа: VPN (ru, вектор-0), отпуск (ru, вектор-1), api-guide (en, вектор-2).

    Возвращает (collection_id, vpn_document_id).
    """
    collection = await CollectionRepository(session).create(
        tenant_id, name=f"c-{uuid.uuid4().hex[:6]}", embedding_model="BAAI/bge-m3"
    )
    source = await SourceRepository(session).create(
        tenant_id, collection_id=collection.id, type_=SourceType.UPLOAD, name="u"
    )
    docs_repo = DocumentRepository(session)
    chunks_repo = ChunkRepository(session)

    corpus = [
        ("vpn.md", "Настройка корпоративного VPN выполняется клиентом WireGuard.", 0, "ru"),
        ("vacation.md", "Отпуск составляет двадцать восемь календарных дней.", 1, "ru"),
        ("api.md", "The API guide describes authentication endpoints.", 2, "en"),
    ]
    vpn_doc_id: uuid.UUID | None = None
    for filename, text, direction, lang in corpus:
        document = await docs_repo.create(
            tenant_id, source_id=source.id, external_id=filename, title=filename
        )
        version = await docs_repo.create_version(
            tenant_id, document_id=document.id, content_hash=f"h-{filename}"
        )
        await chunks_repo.bulk_upsert(
            tenant_id,
            [
                {
                    "document_version_id": version.id,
                    "collection_id": collection.id,
                    "ordinal": 0,
                    "text": text,
                    "embedding": unit_vector(direction),
                    "token_count": len(text.split()),
                    "meta": {"doc_title": filename, "lang": lang, "source_type": "upload"},
                }
            ],
        )
        await docs_repo.activate_version(tenant_id, document.id, version.id)
        if filename == "vpn.md":
            vpn_doc_id = document.id
    await session.commit()
    assert vpn_doc_id is not None
    return collection.id, vpn_doc_id


async def test_bm25_finds_exact_term(db_session: AsyncSession, tenant_id: uuid.UUID) -> None:
    collection_id, _ = await seed_corpus(db_session, tenant_id)
    results = await Bm25Store(db_session).search(
        "WireGuard",
        tenant_id=tenant_id,
        filters=SearchFilters(collection_id=collection_id),
        access_context=AccessContext(),
        top_k=10,
    )
    assert results and "VPN" in results[0].text
    assert results[0].bm25_rank == 1


async def test_vector_channel_ranks_by_cosine(
    db_session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    collection_id, _ = await seed_corpus(db_session, tenant_id)
    results = await PgVectorStore(db_session).search(
        unit_vector(1),
        tenant_id=tenant_id,
        filters=SearchFilters(collection_id=collection_id),
        access_context=AccessContext(),
        top_k=2,
    )
    assert results[0].text.startswith("Отпуск")
    assert results[0].vector_rank == 1


async def test_superseded_version_invisible(db_session: AsyncSession, tenant_id: uuid.UUID) -> None:
    collection_id, vpn_doc_id = await seed_corpus(db_session, tenant_id)
    docs_repo = DocumentRepository(db_session)
    version2 = await docs_repo.create_version(
        tenant_id, document_id=vpn_doc_id, content_hash="h-vpn-2"
    )
    await ChunkRepository(db_session).bulk_upsert(
        tenant_id,
        [
            {
                "document_version_id": version2.id,
                "collection_id": collection_id,
                "ordinal": 0,
                "text": "Новая инструкция VPN: клиент OpenVPN вместо WireGuard.",
                "embedding": unit_vector(0),
                "token_count": 8,
                "meta": {"doc_title": "vpn.md", "lang": "ru", "source_type": "upload"},
            }
        ],
    )
    await docs_repo.activate_version(tenant_id, vpn_doc_id, version2.id)
    await db_session.commit()

    results = await Bm25Store(db_session).search(
        "VPN",
        tenant_id=tenant_id,
        filters=SearchFilters(collection_id=collection_id),
        access_context=AccessContext(),
        top_k=10,
    )
    texts = [r.text for r in results]
    assert any("OpenVPN" in t for t in texts)
    assert not any("выполняется клиентом WireGuard" in t for t in texts)  # v1 скрыта


async def test_lang_filter(db_session: AsyncSession, tenant_id: uuid.UUID) -> None:
    collection_id, _ = await seed_corpus(db_session, tenant_id)
    results = await PgVectorStore(db_session).search(
        unit_vector(2),
        tenant_id=tenant_id,
        filters=SearchFilters(collection_id=collection_id, lang="ru"),
        access_context=AccessContext(),
        top_k=10,
    )
    assert results and all(r.meta["lang"] == "ru" for r in results)


@pytest.fixture()
async def committed_corpus(
    migrated_db: Settings, tenant_id: uuid.UUID
) -> "AsyncIterator[tuple[async_sessionmaker[AsyncSession], uuid.UUID]]":
    """Корпус, закоммиченный по-настоящему: параллельные каналы retriever'а
    работают в собственных сессиях и не видят savepoint-данные db_session."""
    dsn = migrated_db.database_dsn.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(dsn)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        collection_id, _ = await seed_corpus(session, tenant_id)
    yield maker, collection_id
    async with maker() as session:
        await session.execute(delete(Chunk).where(Chunk.collection_id == collection_id))
        await session.execute(
            update(Document)
            .where(
                Document.source_id.in_(
                    select(Source.id).where(Source.collection_id == collection_id)
                )
            )
            .values(active_version_id=None)
        )
        await session.execute(
            delete(DocumentVersion).where(
                DocumentVersion.document_id.in_(
                    select(Document.id).where(
                        Document.source_id.in_(
                            select(Source.id).where(Source.collection_id == collection_id)
                        )
                    )
                )
            )
        )
        await session.execute(
            delete(Document).where(
                Document.source_id.in_(
                    select(Source.id).where(Source.collection_id == collection_id)
                )
            )
        )
        await session.execute(delete(Source).where(Source.collection_id == collection_id))
        await session.execute(delete(Collection).where(Collection.id == collection_id))
        await session.commit()
    await engine.dispose()


def _retriever(
    maker: "async_sessionmaker[AsyncSession]", *, reranker_url: str = "http://reranker-test"
) -> HybridRetriever:
    settings = Settings(_env_file=None).model_copy(update={"reranker_url": reranker_url})
    return HybridRetriever(
        maker,
        settings,
        embedding_client=FakeEmbeddings(),  # type: ignore[arg-type]
        retrieval_cache=NullCache(),  # type: ignore[arg-type]
    )


@respx.mock
async def test_hybrid_retrieve_with_rerank(
    committed_corpus: "tuple[async_sessionmaker[AsyncSession], uuid.UUID]",
    tenant_id: uuid.UUID,
) -> None:
    maker, collection_id = committed_corpus

    def rerank_mock(request: Any) -> Response:
        body = json.loads(request.read())
        return Response(
            200,
            json=[{"index": i, "score": 0.1 * (i + 1)} for i in range(len(body["texts"]))],
        )

    respx.post("http://reranker-test/rerank").mock(side_effect=rerank_mock)
    result = await _retriever(maker).retrieve(
        "вектор-0 VPN WireGuard",
        tenant_id=tenant_id,
        filters=SearchFilters(collection_id=collection_id),
        top_k=3,
    )
    assert not result.degraded
    assert result.chunks and all(c.rerank_score is not None for c in result.chunks)


@respx.mock
async def test_reranker_down_graceful_degradation(
    committed_corpus: "tuple[async_sessionmaker[AsyncSession], uuid.UUID]",
    tenant_id: uuid.UUID,
) -> None:
    maker, collection_id = committed_corpus
    respx.post("http://reranker-test/rerank").mock(return_value=Response(503))
    result = await _retriever(maker).retrieve(
        "вектор-0 VPN",
        tenant_id=tenant_id,
        filters=SearchFilters(collection_id=collection_id),
        top_k=3,
    )
    assert result.degraded  # RRF-порядок, но поиск жив
    assert result.chunks
    assert result.chunks[0].rerank_score is None


async def test_result_cache_roundtrip(migrated_db: Settings, tenant_id: uuid.UUID) -> None:
    """Сериализация ScoredChunk в Redis-кэш и обратно (реальный Redis из compose)."""
    cache = RetrievalCache(Settings(_env_file=None).redis_url)

    chunk_id = uuid.uuid4()
    original = ScoredChunk(
        chunk_id=chunk_id,
        document_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        ordinal=1,
        text="кэшируемый текст",
        token_count=2,
        meta={"lang": "ru"},
        embedding=[0.1] * 4,
        bm25_rank=1,
        vector_rank=None,
        rrf_score=0.032,
        rerank_score=0.9,
    )
    key = cache_module.result_key("q", uuid.uuid4(), SearchFilters(), 5, True)
    await cache.set_result(key, [original])
    restored = await cache.get_result(key)
    if restored is None:
        pytest.skip("Redis недоступен — кэш работает в fail-open режиме")
    assert restored[0].chunk_id == chunk_id
    assert restored[0].rerank_score == 0.9
    assert restored[0].embedding is None  # эмбеддинги в кэш не пишутся
