"""RRF-слияние каналов (ADR-005): score(d) = Σ 1/(k + rank_канал(d)), k=60.

Работает по рангам — нормализация разнородных скор BM25/cosine не нужна.
Детерминированность: при равном score порядок стабилен (по chunk_id).
"""

from lyra.retrieval.interfaces import ScoredChunk

RRF_K = 60


class RRFFuser:
    def __init__(self, k: int = RRF_K) -> None:
        self._k = k

    def fuse(self, channels: list[list[ScoredChunk]]) -> list[ScoredChunk]:
        merged: dict[str, ScoredChunk] = {}
        for channel in channels:
            for rank, item in enumerate(channel, start=1):
                key = str(item.chunk_id)
                if key in merged:
                    existing = merged[key]
                    # Сливаем канальные ранги в один объект
                    existing.bm25_rank = existing.bm25_rank or item.bm25_rank
                    existing.vector_rank = existing.vector_rank or item.vector_rank
                    existing.rrf_score += 1.0 / (self._k + rank)
                else:
                    item.rrf_score = 1.0 / (self._k + rank)
                    merged[key] = item
        return sorted(merged.values(), key=lambda c: (-c.rrf_score, str(c.chunk_id)))
