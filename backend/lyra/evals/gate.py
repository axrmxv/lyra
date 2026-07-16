"""Гейт качества: пороги thresholds.yaml + регресс против baseline.

Пороги НЕ снижаются ради зелёного CI (.claude/rules/evals.md); падение
любой гейт-метрики > max_baseline_drop относительно baseline — красный,
даже если абсолютный порог пройден (eval-plan §4).
"""

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from lyra.evals.metrics import GATE_METRICS


class Threshold(BaseModel):
    min: float | None = None
    max: float | None = None


class Thresholds(BaseModel):
    max_baseline_drop: float = 0.05
    metrics: dict[str, Threshold]


class GateFailure(BaseModel):
    metric: str
    value: float | None
    reason: str


class GateResult(BaseModel):
    passed: bool
    failures: list[GateFailure]


def load_thresholds(path: Path) -> Thresholds:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Thresholds.model_validate(data)


def load_baseline(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    parsed: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return parsed


def evaluate_gate(
    aggregates: dict[str, Any],
    thresholds: Thresholds,
    baseline: dict[str, Any] | None,
) -> GateResult:
    failures: list[GateFailure] = []

    for metric, threshold in thresholds.metrics.items():
        value = aggregates.get(metric)
        if value is None:
            failures.append(GateFailure(metric=metric, value=None, reason="метрика не посчитана"))
            continue
        if threshold.min is not None and value < threshold.min:
            failures.append(
                GateFailure(metric=metric, value=value, reason=f"ниже порога {threshold.min}")
            )
        if threshold.max is not None and value > threshold.max:
            failures.append(
                GateFailure(metric=metric, value=value, reason=f"выше порога {threshold.max}")
            )

    if baseline:
        baseline_metrics: dict[str, Any] = baseline.get("metrics", baseline)
        for metric in GATE_METRICS:
            value = aggregates.get(metric)
            base = baseline_metrics.get(metric)
            if value is None or base is None:
                continue
            # Для false_refusal_rate «хуже» = рост; для остальных — падение
            drop = (value - base) if metric == "false_refusal_rate" else (base - value)
            if drop > thresholds.max_baseline_drop:
                failures.append(
                    GateFailure(
                        metric=metric,
                        value=value,
                        reason=(
                            f"регресс {drop:+.3f} от baseline {base} "
                            f"(допустимо {thresholds.max_baseline_drop})"
                        ),
                    )
                )

    return GateResult(passed=not failures, failures=failures)


def baseline_deltas(
    aggregates: dict[str, Any], baseline: dict[str, Any] | None
) -> dict[str, float]:
    if not baseline:
        return {}
    baseline_metrics: dict[str, Any] = baseline.get("metrics", baseline)
    deltas: dict[str, float] = {}
    for metric in GATE_METRICS:
        value = aggregates.get(metric)
        base = baseline_metrics.get(metric)
        if value is not None and base is not None:
            deltas[metric] = round(value - base, 4)
    return deltas
