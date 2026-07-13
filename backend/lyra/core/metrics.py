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

# LLM-вызовы (FR-19, ADR-009): каждый вызов трейсится с узлом графа
LLM_CALL_SECONDS = Histogram(
    "lyra_llm_call_seconds",
    "Длительность LLM-вызовов",
    ["node", "model"],
    buckets=(0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 60.0),
)
LLM_TOKENS = Counter("lyra_llm_tokens_total", "Токены LLM-вызовов", ["node", "direction"])
