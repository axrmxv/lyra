"""Prometheus-метрики (FR-20). Единая точка объявления — без дублей регистрации."""

from prometheus_client import Counter, Histogram

RETRIEVAL_STEP_SECONDS = Histogram(
    "lyra_retrieval_step_seconds",
    "Длительность шагов retrieval-пайплайна",
    ["step"],  # embed_query | bm25 | vector | fuse | rerank | postprocess
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
)

CACHE_HITS = Counter("lyra_cache_hits_total", "Попадания в кэш", ["cache"])
CACHE_MISSES = Counter("lyra_cache_misses_total", "Промахи кэша", ["cache"])

RETRIEVAL_DEGRADED = Counter(
    "lyra_retrieval_degraded_total",
    "Запросы с деградацией (reranker недоступен)",
)
