"""Постобработка кандидатов (docs/context-management.md §3):

- дедуп точных копий текста (копии документов) — остаётся лучший по score;
- MMR (λ=0.7): разнообразие контекста вместо восьми вариантов одного абзаца;
- склейка соседних chunks одного документа — используется сборкой контекста
  LLM (фаза 4); /search отдаёт chunks без склейки.
"""

import math

from lyra.retrieval.interfaces import ScoredChunk

MMR_LAMBDA = 0.7


def dedup_exact(chunks: list[ScoredChunk]) -> list[ScoredChunk]:
    seen: dict[str, ScoredChunk] = {}
    for chunk in chunks:  # вход отсортирован по score — первый и есть лучший
        seen.setdefault(chunk.text, chunk)
    return list(seen.values())


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def mmr_select(
    chunks: list[ScoredChunk], *, top_k: int, lambda_: float = MMR_LAMBDA
) -> list[ScoredChunk]:
    """Maximal marginal relevance по эмбеддингам кандидатов.

    Релевантность — нормированный final_score (позиции входа уже ранжированы);
    кандидаты без эмбеддинга проходят по релевантности без штрафа.
    """
    if len(chunks) <= top_k:
        return chunks
    scores = [chunk.final_score for chunk in chunks]
    low, high = min(scores), max(scores)
    span = (high - low) or 1.0
    relevance = [(score - low) / span for score in scores]

    selected: list[int] = []
    remaining = list(range(len(chunks)))
    while remaining and len(selected) < top_k:
        best_index, best_value = remaining[0], -math.inf
        for index in remaining:
            embedding = chunks[index].embedding
            if embedding is None or not selected:
                max_sim = 0.0
            else:
                selected_embeddings = [
                    emb for s in selected if (emb := chunks[s].embedding) is not None
                ]
                max_sim = max((_cosine(embedding, emb) for emb in selected_embeddings), default=0.0)
            value = lambda_ * relevance[index] - (1 - lambda_) * max_sim
            if value > best_value:
                best_index, best_value = index, value
        selected.append(best_index)
        remaining.remove(best_index)
    return [chunks[i] for i in selected]


def merge_neighbors(chunks: list[ScoredChunk]) -> list[ScoredChunk]:
    """Соседние chunks одного документа (ordinal подряд) → один блок.

    Тексты склеиваются в порядке ordinal, скоры — от лучшего из пары.
    Для сборки контекста LLM; порядок результата — по лучшему score группы.
    """
    by_version: dict[str, list[ScoredChunk]] = {}
    for chunk in chunks:
        by_version.setdefault(str(chunk.document_version_id), []).append(chunk)

    merged: list[ScoredChunk] = []
    for group in by_version.values():
        group.sort(key=lambda c: c.ordinal)
        run: list[ScoredChunk] = []
        for chunk in group:
            if run and chunk.ordinal == run[-1].ordinal + 1:
                run.append(chunk)
            else:
                if run:
                    merged.append(_merge_run(run))
                run = [chunk]
        if run:
            merged.append(_merge_run(run))
    return sorted(merged, key=lambda c: -c.final_score)


def _merge_run(run: list[ScoredChunk]) -> ScoredChunk:
    if len(run) == 1:
        return run[0]
    best = max(run, key=lambda c: c.final_score)
    # Префикс "{doc_title} > {path}" оставляем только у первого фрагмента
    parts = [run[0].text] + [chunk.text.split("\n\n", 1)[-1] for chunk in run[1:]]
    merged = ScoredChunk(
        chunk_id=best.chunk_id,
        document_id=best.document_id,
        document_version_id=best.document_version_id,
        ordinal=run[0].ordinal,
        text="\n\n".join(parts),
        token_count=sum(chunk.token_count for chunk in run),
        meta=best.meta,
        embedding=None,
        bm25_rank=best.bm25_rank,
        vector_rank=best.vector_rank,
        rrf_score=best.rrf_score,
        rerank_score=best.rerank_score,
    )
    return merged
