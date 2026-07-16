"""Юнит-тесты evals: детерминированные метрики, агрегаты, гейт, thresholds."""

import uuid
from pathlib import Path

import pytest

from lyra.evals.gate import Thresholds, baseline_deltas, evaluate_gate, load_thresholds
from lyra.evals.metrics import (
    ItemScores,
    aggregate,
    context_recall,
    hit_at_k,
    markers_deterministically_valid,
    paraphrase_spread,
    split_sentences_with_markers,
    weighted_context_precision,
)
from lyra.rag.state import CitationItem

THRESHOLDS_PATH = Path(__file__).parents[2] / "evals" / "thresholds.yaml"

DOC_A, DOC_B, DOC_C = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def make_citation(marker: int, chunk_id: uuid.UUID | None = None) -> CitationItem:
    return CitationItem(
        id=marker,
        chunk_id=chunk_id or uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_title="Документ",
        url=None,
        quote="цитата",
        relevance_score=0.9,
    )


def test_context_recall_full_and_partial() -> None:
    assert context_recall({DOC_A, DOC_B}, [DOC_A, DOC_B, DOC_C]) == 1.0
    assert context_recall({DOC_A, DOC_B}, [DOC_A, DOC_C]) == 0.5
    assert context_recall({DOC_A}, [DOC_B]) == 0.0
    assert context_recall(set(), [DOC_A]) is None  # unanswerable — неприменимо


def test_hit_at_k_respects_position() -> None:
    assert hit_at_k({DOC_A}, [DOC_B, DOC_A, DOC_C], k=2) == 1.0
    assert hit_at_k({DOC_A}, [DOC_B, DOC_C, DOC_A], k=2) == 0.0
    assert hit_at_k(set(), [DOC_A], k=5) is None


def test_markers_deterministic_validation() -> None:
    chunk_id = uuid.uuid4()
    citations = [make_citation(1, chunk_id), make_citation(2)]
    context_ids = {chunk_id}
    verdicts = markers_deterministically_valid(
        "Ответ [1] и ещё [2] и битый [7].", citations, context_ids
    )
    assert verdicts[1] is True  # citation есть, chunk в контексте
    assert verdicts[2] is False  # chunk не из контекста
    assert verdicts[7] is False  # маркер без citation


def test_split_sentences_with_markers() -> None:
    sentences = split_sentences_with_markers("Первое [1]. Без маркера. Второе [2][3]!")
    assert len(sentences) == 2
    assert sentences[0][1] == [1]
    assert sentences[1][1] == [2, 3]


def test_weighted_context_precision() -> None:
    assert weighted_context_precision([True, True]) == 1.0
    # Релевантный на 2-й позиции: precision@2 = 1/2
    assert weighted_context_precision([False, True]) == 0.5
    assert weighted_context_precision([True, False]) == 1.0
    assert weighted_context_precision([False, False]) == 0.0
    assert weighted_context_precision([]) == 0.0


def _score(**overrides: object) -> ItemScores:
    base: dict[str, object] = {
        "item_id": "x",
        "kind": "answerable",
        "subset": "single_chunk",
        "refusal": False,
        "llm_calls": 3,
        "took_ms": 100,
    }
    base.update(overrides)
    return ItemScores.model_validate(base)


def test_aggregate_refusal_rates_and_means() -> None:
    scores = [
        _score(item_id="a", faithfulness=1.0, context_recall=1.0),
        _score(item_id="b", faithfulness=0.5, context_recall=0.5, refusal=True),
        _score(item_id="u1", kind="unanswerable", subset="unanswerable", refusal=True),
        _score(item_id="u2", kind="unanswerable", subset="unanswerable", refusal=False),
    ]
    aggregates = aggregate(scores)
    assert aggregates["faithfulness"] == 0.75
    assert aggregates["context_recall"] == 0.75
    assert aggregates["honest_refusal_rate"] == 0.5  # 1 из 2 unanswerable
    assert aggregates["false_refusal_rate"] == 0.5  # 1 из 2 answerable
    assert aggregates["items_total"] == 4


def test_paraphrase_spread_flags_instability() -> None:
    scores = [
        _score(item_id="p1", kind="paraphrase", paraphrase_group="g", faithfulness=1.0),
        _score(item_id="p2", kind="paraphrase", paraphrase_group="g", faithfulness=0.7),
    ]
    spread = paraphrase_spread(scores)
    assert spread["g"] == pytest.approx(0.3)


def test_thresholds_parser_reads_repo_file() -> None:
    thresholds = load_thresholds(THRESHOLDS_PATH)
    assert thresholds.metrics["faithfulness"].min == 0.85
    assert thresholds.metrics["false_refusal_rate"].max == 0.10
    assert thresholds.max_baseline_drop == 0.05


def _passing_aggregates() -> dict[str, object]:
    return {
        "faithfulness": 0.9,
        "answer_relevance": 0.85,
        "context_precision": 0.8,
        "context_recall": 0.8,
        "citation_validity": 0.96,
        "honest_refusal_rate": 1.0,
        "false_refusal_rate": 0.0,
    }


def test_gate_passes_and_fails_on_threshold() -> None:
    thresholds = load_thresholds(THRESHOLDS_PATH)
    assert evaluate_gate(_passing_aggregates(), thresholds, None).passed

    bad = _passing_aggregates() | {"faithfulness": 0.7}
    result = evaluate_gate(bad, thresholds, None)
    assert not result.passed
    assert result.failures[0].metric == "faithfulness"

    # false_refusal_rate — порог сверху
    bad_refusal = _passing_aggregates() | {"false_refusal_rate": 0.2}
    assert not evaluate_gate(bad_refusal, thresholds, None).passed


def test_gate_fails_on_baseline_regression() -> None:
    thresholds = load_thresholds(THRESHOLDS_PATH)
    aggregates = _passing_aggregates() | {"faithfulness": 0.87}
    baseline = {"metrics": _passing_aggregates() | {"faithfulness": 0.95}}
    result = evaluate_gate(aggregates, thresholds, baseline)
    # 0.95 → 0.87 = падение 0.08 > 0.05, хотя порог 0.85 пройден
    assert not result.passed
    assert "регресс" in result.failures[0].reason

    deltas = baseline_deltas(aggregates, baseline)
    assert deltas["faithfulness"] == pytest.approx(-0.08)


def test_gate_missing_metric_fails() -> None:
    thresholds = Thresholds.model_validate({"metrics": {"faithfulness": {"min": 0.85}}})
    result = evaluate_gate({"faithfulness": None}, thresholds, None)
    assert not result.passed
    assert result.failures[0].reason == "метрика не посчитана"
