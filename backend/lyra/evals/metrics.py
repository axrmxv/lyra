"""Метрики evals — формулы строго по docs/eval-plan.md §1.

Детерминированные (context_recall, валидация маркеров, refusal rates,
hit@k) считаются без LLM; faithfulness / answer_relevance /
context_precision / поддержка цитат — через Judge. Judge-вызовы этих
метрик не подменяют детерминированные части (.claude/rules/evals.md).
"""

import re
import statistics
import uuid
from typing import Any

from pydantic import BaseModel

from lyra.evals.judge import Judge
from lyra.rag.state import CitationItem
from lyra.retrieval.interfaces import ScoredChunk

MARKER_RE = re.compile(r"\[(\d+)\]")

GATE_METRICS = (
    "faithfulness",
    "answer_relevance",
    "context_precision",
    "context_recall",
    "citation_validity",
    "honest_refusal_rate",
    "false_refusal_rate",
)


class ItemScores(BaseModel):
    """Метрики одного item; None = метрика неприменима к этому item."""

    item_id: str
    kind: str
    subset: str
    paraphrase_group: str | None = None
    refusal: bool
    faithfulness: float | None = None
    answer_relevance: float | None = None
    context_precision: float | None = None
    context_recall: float | None = None
    citation_validity: float | None = None
    hit_at_k_pre_rerank: float | None = None
    hit_at_k_post_rerank: float | None = None
    llm_calls: int = 0
    took_ms: int = 0
    corrective_iterations: int = 0
    generate_retries: int = 0
    trace_id: str = ""
    answer: str = ""


# --- Детерминированные метрики ---


def context_recall(
    expected_doc_ids: set[uuid.UUID], retrieved_doc_ids: list[uuid.UUID]
) -> float | None:
    """Доля ожидаемых документов, найденных retrieval'ом (doc-level разметка)."""
    if not expected_doc_ids:
        return None
    found = expected_doc_ids & set(retrieved_doc_ids)
    return len(found) / len(expected_doc_ids)


def hit_at_k(
    expected_doc_ids: set[uuid.UUID], retrieved_doc_ids: list[uuid.UUID], k: int
) -> float | None:
    """Доля ожидаемых документов в top-k выдачи."""
    if not expected_doc_ids:
        return None
    top = set(retrieved_doc_ids[:k])
    return len(expected_doc_ids & top) / len(expected_doc_ids)


def split_sentences_with_markers(answer: str) -> list[tuple[str, list[int]]]:
    """Предложения ответа с их маркерами [n] (для judge поддержки цитат)."""
    sentences = re.split(r"(?<=[.!?])\s+", answer.strip())
    result: list[tuple[str, list[int]]] = []
    for sentence in sentences:
        markers = [int(m) for m in MARKER_RE.findall(sentence)]
        if markers:
            result.append((sentence, markers))
    return result


def markers_deterministically_valid(
    answer: str, citations: list[CitationItem], context_chunk_ids: set[uuid.UUID]
) -> dict[int, bool]:
    """Маркер валиден детерминированно: есть citation с этим id и её chunk
    входил в переданный контекст (ADR-007, узел cite)."""
    by_id = {citation.id: citation for citation in citations}
    verdicts: dict[int, bool] = {}
    for marker in {int(m) for m in MARKER_RE.findall(answer)}:
        citation = by_id.get(marker)
        verdicts[marker] = citation is not None and citation.chunk_id in context_chunk_ids
    return verdicts


async def citation_validity(
    judge: Judge,
    answer: str,
    citations: list[CitationItem],
    context_chunks: list[ScoredChunk],
) -> float | None:
    """Доля валидных цитат: детерминированная проверка маркера + judge
    подтверждения утверждения текстом процитированного chunk."""
    chunk_by_id = {chunk.chunk_id: chunk for chunk in context_chunks}
    deterministic = markers_deterministically_valid(answer, citations, set(chunk_by_id.keys()))
    if not deterministic:
        return None  # ответ без цитат (например, отказ) — метрика неприменима

    citation_by_id = {citation.id: citation for citation in citations}
    total = 0
    valid = 0
    for sentence, markers in split_sentences_with_markers(answer):
        for marker in markers:
            total += 1
            if not deterministic.get(marker, False):
                continue
            chunk_id = citation_by_id[marker].chunk_id
            chunk = chunk_by_id.get(chunk_id) if chunk_id else None
            if chunk is None:
                continue
            if await judge.citation_supported(sentence, chunk.text):
                valid += 1
    if total == 0:
        return None
    return valid / total


def weighted_context_precision(relevance_flags: list[bool]) -> float:
    """Precision@k со взвешиванием по позиции (формула RAGAS):
    sum(precision@i * rel_i) / count(relevant)."""
    if not relevance_flags:
        return 0.0
    relevant_total = sum(relevance_flags)
    if relevant_total == 0:
        return 0.0
    score = 0.0
    seen_relevant = 0
    for index, flag in enumerate(relevance_flags, start=1):
        if flag:
            seen_relevant += 1
            score += seen_relevant / index
    return score / relevant_total


# --- Judge-метрики ---


async def faithfulness_score(judge: Judge, answer: str, context_text: str) -> float | None:
    verdict = await judge.faithfulness(answer, context_text)
    if not verdict.claims:
        return None
    supported = sum(1 for claim in verdict.claims if claim.supported)
    return supported / len(verdict.claims)


async def context_precision_score(
    judge: Judge, question: str, ground_truth: str | None, context_chunks: list[ScoredChunk]
) -> float | None:
    if not context_chunks:
        return None
    flags = [
        await judge.chunk_relevant(question, ground_truth, chunk.text) for chunk in context_chunks
    ]
    return weighted_context_precision(flags)


# --- Агрегация ---


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def aggregate(scores: list[ItemScores]) -> dict[str, Any]:
    """Агрегаты run'а: гейт-метрики + вспомогательные (eval-plan §1)."""
    answerable = [s for s in scores if s.kind in ("answerable", "paraphrase")]
    unanswerable = [s for s in scores if s.kind == "unanswerable"]

    def collect(name: str, subset: list[ItemScores]) -> list[float]:
        return [v for s in subset if (v := getattr(s, name)) is not None]

    aggregates: dict[str, Any] = {
        "faithfulness": _mean(collect("faithfulness", answerable)),
        "answer_relevance": _mean(collect("answer_relevance", answerable)),
        "context_precision": _mean(collect("context_precision", answerable)),
        "context_recall": _mean(collect("context_recall", answerable)),
        "citation_validity": _mean(collect("citation_validity", answerable)),
        "honest_refusal_rate": (
            _mean([1.0 if s.refusal else 0.0 for s in unanswerable]) if unanswerable else None
        ),
        "false_refusal_rate": (
            _mean([1.0 if s.refusal else 0.0 for s in answerable]) if answerable else None
        ),
        # Вспомогательные — не гейт, наблюдаем в динамике
        "hit_at_k_pre_rerank": _mean(collect("hit_at_k_pre_rerank", answerable)),
        "hit_at_k_post_rerank": _mean(collect("hit_at_k_post_rerank", answerable)),
        "avg_llm_calls": _mean([float(s.llm_calls) for s in scores]),
        "p50_took_ms": (int(statistics.median([s.took_ms for s in scores])) if scores else None),
        "corrective_rate": _mean([1.0 if s.corrective_iterations > 0 else 0.0 for s in scores]),
        "retry_rate": _mean([1.0 if s.generate_retries > 0 else 0.0 for s in scores]),
        "items_total": len(scores),
    }
    return aggregates


def paraphrase_spread(scores: list[ItemScores]) -> dict[str, float]:
    """Максимальное расхождение faithfulness/relevance внутри paraphrase-групп:
    > 0.1 — сигнал нестабильности промпта/retrieval (eval-plan §5)."""
    groups: dict[str, list[ItemScores]] = {}
    for score in scores:
        if score.paraphrase_group:
            groups.setdefault(score.paraphrase_group, []).append(score)
    spreads: dict[str, float] = {}
    for group, members in groups.items():
        deltas: list[float] = []
        for metric in ("faithfulness", "answer_relevance"):
            values = [v for s in members if (v := getattr(s, metric)) is not None]
            if len(values) >= 2:
                deltas.append(max(values) - min(values))
        if deltas:
            spreads[group] = round(max(deltas), 4)
    return spreads
