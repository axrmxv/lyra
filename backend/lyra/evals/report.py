"""Отчёты eval-run: JSON-артефакт и markdown (для PR-комментария)."""

import json
from pathlib import Path
from typing import Any

from lyra.evals.gate import GateResult, Thresholds
from lyra.evals.metrics import GATE_METRICS, ItemScores


def worst_items(scores: list[ItemScores], n: int = 5) -> list[ItemScores]:
    """Худшие items: сортировка по faithfulness, citation_validity, relevance."""

    def sort_key(score: ItemScores) -> tuple[float, float, float]:
        return (
            score.faithfulness if score.faithfulness is not None else 1.0,
            score.citation_validity if score.citation_validity is not None else 1.0,
            score.answer_relevance if score.answer_relevance is not None else 1.0,
        )

    ranked = [s for s in scores if s.kind != "unanswerable"]
    return sorted(ranked, key=sort_key)[:n]


def build_json_report(
    *,
    run_id: str,
    aggregates: dict[str, Any],
    gate: GateResult,
    deltas: dict[str, float],
    scores: list[ItemScores],
    spreads: dict[str, float],
    config_snapshot: dict[str, Any],
    unreviewed_used: bool,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "metrics": aggregates,
        "gate": gate.model_dump(),
        "baseline_delta": deltas,
        "paraphrase_spread": spreads,
        "unreviewed_used": unreviewed_used,
        "worst_items": [
            {
                "item_id": s.item_id,
                "faithfulness": s.faithfulness,
                "citation_validity": s.citation_validity,
                "answer_relevance": s.answer_relevance,
                "trace_id": s.trace_id,
                "answer": s.answer[:300],
            }
            for s in worst_items(scores)
        ],
        "items": [s.model_dump() for s in scores],
        "config_snapshot": config_snapshot,
    }


def _format_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def build_markdown_report(
    *,
    run_id: str,
    aggregates: dict[str, Any],
    gate: GateResult,
    thresholds: Thresholds,
    deltas: dict[str, float],
    scores: list[ItemScores],
    spreads: dict[str, float],
    unreviewed_used: bool,
) -> str:
    lines = [
        f"## Eval-run `{run_id}` — {'✅ гейт пройден' if gate.passed else '❌ гейт не пройден'}",
        "",
        "| Метрика | Значение | Порог | Δ к baseline |",
        "|---------|----------|-------|--------------|",
    ]
    for metric in GATE_METRICS:
        threshold = thresholds.metrics.get(metric)
        bound = "—"
        if threshold:
            bound = f"≥ {threshold.min}" if threshold.min is not None else f"≤ {threshold.max}"
        delta = deltas.get(metric)
        delta_text = f"{delta:+.3f}" if delta is not None else "—"
        lines.append(
            f"| {metric} | {_format_value(aggregates.get(metric))} | {bound} | {delta_text} |"
        )

    lines += [
        "",
        f"Вспомогательные: hit@k до/после rerank "
        f"{_format_value(aggregates.get('hit_at_k_pre_rerank'))} → "
        f"{_format_value(aggregates.get('hit_at_k_post_rerank'))}, "
        f"corrective-rate {_format_value(aggregates.get('corrective_rate'))}, "
        f"среднее LLM-вызовов {_format_value(aggregates.get('avg_llm_calls'))}, "
        f"p50 {_format_value(aggregates.get('p50_took_ms'))} мс, "
        f"items: {aggregates.get('items_total')}.",
    ]

    if unreviewed_used:
        lines += [
            "",
            "⚠️ В прогон включены item'ы без ручного ревью (`reviewed: false`) — "
            "результат не является официальным гейтом golden set.",
        ]

    if not gate.passed:
        lines += ["", "### Провалы гейта", ""]
        lines += [
            f"- **{failure.metric}** = {_format_value(failure.value)}: {failure.reason}"
            for failure in gate.failures
        ]

    bad_spreads = {g: v for g, v in spreads.items() if v > 0.1}
    if bad_spreads:
        lines += ["", "### Paraphrase-расхождения > 0.1", ""]
        lines += [f"- `{group}`: {value:.3f}" for group, value in bad_spreads.items()]

    lines += ["", "### Worst-5 items", ""]
    lines += [
        "| item | faithfulness | citation_validity | relevance | trace_id |",
        "|------|--------------|-------------------|-----------|----------|",
    ]
    for s in worst_items(scores):
        lines.append(
            f"| {s.item_id} | {_format_value(s.faithfulness)} | "
            f"{_format_value(s.citation_validity)} | "
            f"{_format_value(s.answer_relevance)} | `{s.trace_id}` |"
        )
    return "\n".join(lines) + "\n"


def write_reports(
    output_dir: Path, json_report: dict[str, Any], markdown_report: str
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "eval-report.json"
    md_path = output_dir / "eval-report.md"
    json_path.write_text(
        json.dumps(json_report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    md_path.write_text(markdown_report, encoding="utf-8")
    return json_path, md_path
