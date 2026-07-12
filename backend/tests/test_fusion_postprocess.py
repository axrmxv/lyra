"""Юнит-тесты RRF, MMR, дедупа, склейки соседей и ключей кэша — детерминированные."""

import uuid

from lyra.retrieval import cache as cache_module
from lyra.retrieval.fusion import RRFFuser
from lyra.retrieval.interfaces import ScoredChunk, SearchFilters
from lyra.retrieval.postprocess import dedup_exact, merge_neighbors, mmr_select


def make_chunk(
    text: str,
    *,
    ordinal: int = 0,
    version: uuid.UUID | None = None,
    embedding: list[float] | None = None,
    rrf: float = 0.0,
    rerank: float | None = None,
) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_version_id=version or uuid.uuid4(),
        ordinal=ordinal,
        text=text,
        token_count=len(text.split()),
        meta={},
        embedding=embedding,
        rrf_score=rrf,
        rerank_score=rerank,
    )


# --- RRF (формула из ADR-005, k=60) ---


def test_rrf_formula_both_channels() -> None:
    shared = make_chunk("общий")
    only_bm25 = make_chunk("лексический")
    only_vector = make_chunk("семантический")
    fused = RRFFuser().fuse([[shared, only_bm25], [shared, only_vector]])

    scores = {c.text: c.rrf_score for c in fused}
    assert abs(scores["общий"] - (1 / 61 + 1 / 61)) < 1e-9
    assert abs(scores["лексический"] - 1 / 62) < 1e-9
    assert fused[0].text == "общий"  # документ из обоих каналов выигрывает


def test_rrf_deterministic_tie_break() -> None:
    a, b = make_chunk("a"), make_chunk("b")
    first = RRFFuser().fuse([[a], [b]])
    second = RRFFuser().fuse([[a], [b]])
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]


# --- дедуп и MMR ---


def test_dedup_keeps_best() -> None:
    best = make_chunk("копия", rerank=0.9)
    worse = make_chunk("копия", rerank=0.5)
    assert dedup_exact([best, worse]) == [best]


def test_mmr_prefers_diversity() -> None:
    # Два почти одинаковых вектора + ортогональный с близким score;
    # top-2 включает ортогональный вместо дубля (штраф за похожесть)
    a = make_chunk("тема-1", embedding=[1.0, 0.0], rerank=1.0)
    b = make_chunk("тема-1-дубль", embedding=[0.99, 0.14], rerank=0.98)
    c = make_chunk("тема-2", embedding=[0.0, 1.0], rerank=0.95)
    d = make_chunk("шум", embedding=[0.7, 0.7], rerank=0.5)
    selected = mmr_select([a, b, c, d], top_k=2)
    assert {s.text for s in selected} == {"тема-1", "тема-2"}


def test_mmr_passthrough_when_fits() -> None:
    chunks = [make_chunk("x", rerank=1.0), make_chunk("y", rerank=0.5)]
    assert mmr_select(chunks, top_k=5) == chunks


# --- склейка соседей ---


def test_merge_neighbors_joins_consecutive() -> None:
    version = uuid.uuid4()
    first = make_chunk("Док > Р\n\nпервый", ordinal=3, version=version, rerank=0.9)
    second = make_chunk("Док > Р\n\nвторой", ordinal=4, version=version, rerank=0.7)
    other = make_chunk("Док > Р\n\nдалёкий", ordinal=10, version=version, rerank=0.8)
    merged = merge_neighbors([first, second, other])
    assert len(merged) == 2
    joined = next(c for c in merged if c.ordinal == 3)
    assert joined.text == "Док > Р\n\nпервый\n\nвторой"  # префикс один раз
    assert joined.token_count == first.token_count + second.token_count
    assert joined.rerank_score == 0.9  # лучший из пары


def test_merge_neighbors_different_versions_not_joined() -> None:
    first = make_chunk("a", ordinal=0)
    second = make_chunk("b", ordinal=1)  # другой version (random)
    assert len(merge_neighbors([first, second])) == 2


# --- ключи кэша ---


def test_cache_keys_normalize_query() -> None:
    tenant = uuid.uuid4()
    filters = SearchFilters()
    key_a = cache_module.result_key("  Отпуск  сколько ДНЕЙ ", tenant, filters, 10, True)
    key_b = cache_module.result_key("отпуск сколько дней", tenant, filters, 10, True)
    assert key_a == key_b


def test_cache_keys_include_tenant_filters_params() -> None:
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    filters = SearchFilters()
    base = cache_module.result_key("q", tenant_a, filters, 10, True)
    assert base != cache_module.result_key("q", tenant_b, filters, 10, True)  # tenant
    assert base != cache_module.result_key(
        "q", tenant_a, SearchFilters(lang="ru"), 10, True
    )  # фильтры
    assert base != cache_module.result_key("q", tenant_a, filters, 5, True)  # top_k
    assert base != cache_module.result_key("q", tenant_a, filters, 10, False)  # rerank
