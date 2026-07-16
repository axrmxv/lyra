"""Prometheus-метрики (FR-20). Единая точка объявления — без дублей регистрации."""

from prometheus_client import Counter, Gauge, Histogram

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

# Граф и ingest (FR-20, фаза 6): latency по узлам/шагам, счётчики исходов
GRAPH_NODE_SECONDS = Histogram(
    "lyra_graph_node_seconds",
    "Длительность узлов RAG-графа",
    ["node"],
    buckets=(0.05, 0.25, 1.0, 4.0, 15.0, 60.0, 120.0, 300.0),
)
INGEST_STEP_SECONDS = Histogram(
    "lyra_ingest_step_seconds",
    "Длительность шагов ingest-пайплайна",
    ["step"],  # scan | dedup | chunk | embed | index
    buckets=(0.05, 0.25, 1.0, 4.0, 15.0, 60.0, 300.0),
)
ANSWERS_TOTAL = Counter(
    "lyra_answers_total",
    "Итоговые ответы графа по исходу",
    ["outcome"],  # answered | refusal
)
CORRECTIVE_TOTAL = Counter("lyra_corrective_iterations_total", "Итерации corrective_retrieve")
SELF_CHECK_RETRY_TOTAL = Counter(
    "lyra_self_check_retries_total", "Регенерации после cite-error/self_check"
)
DEGRADED_ANSWERS_TOTAL = Counter(
    "lyra_degraded_answers_total", "Ответы в degraded-режиме (reranker недоступен)"
)
INDEX_CHUNKS = Gauge("lyra_index_chunks", "Число chunks активных версий в индексе")
