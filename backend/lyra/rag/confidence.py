"""Confidence ответа (ADR-007 §5): агрегат sufficiency, rerank-score цитат,
self_check. Веса — константы конфигурации; калибровка — golden dataset (фаза 6).
"""

from lyra.rag.state import Confidence, RagState

WEIGHT_SUFFICIENCY = 0.5
WEIGHT_RERANK = 0.3
WEIGHT_SELF_CHECK = 0.2
HIGH_THRESHOLD = 0.7
MEDIUM_THRESHOLD = 0.4


def compute_confidence(state: RagState, *, refusal: bool) -> Confidence:
    if refusal:
        return Confidence(label="low", score=0.0)

    sufficiency_score = state.sufficiency.score if state.sufficiency else 0.5

    cited_ids = {citation.id for citation in state.citations}
    cited_scores = [
        chunk.rerank_score
        for i, chunk in enumerate(state.context_chunks, start=1)
        if i in cited_ids and chunk.rerank_score is not None
    ]
    # bge-reranker: сигмоида, релевантные пары обычно > 0.01..0.9 — нормируем мягко
    rerank_component = (
        min(1.0, (sum(cited_scores) / len(cited_scores)) * 2) if cited_scores else 0.5
    )

    self_check_component = 1.0 if (state.self_check and state.self_check.passed) else 0.0

    score = (
        WEIGHT_SUFFICIENCY * sufficiency_score
        + WEIGHT_RERANK * rerank_component
        + WEIGHT_SELF_CHECK * self_check_component
    )
    label = "high" if score >= HIGH_THRESHOLD else "medium" if score >= MEDIUM_THRESHOLD else "low"
    return Confidence(label=label, score=round(score, 3))
