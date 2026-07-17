"""CLI eval-контура: python -m lyra.evals {seed,run} (docs/eval-plan.md §3).

Выход run: код 0 — гейт пройден, 1 — провален (для CI).
Пути по умолчанию рассчитаны на запуск из корня репозитория.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from lyra.core.logging import configure_logging
from lyra.evals.runner import run_evals
from lyra.evals.seed import SHOWCASE_COLLECTION_NAME, seed_corpus, seed_demo_users

DEFAULT_CORPUS = Path("evals/corpus")
DEFAULT_DATASET = Path("evals/datasets/golden.jsonl")
DEFAULT_THRESHOLDS = Path("evals/thresholds.yaml")
DEFAULT_BASELINE = Path("evals/baseline.json")
DEFAULT_OUTPUT = Path("evals/reports")


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="python -m lyra.evals")
    sub = parser.add_subparsers(dest="command", required=True)

    seed_parser = sub.add_parser("seed", help="Сид демо-корпуса через ingest-пайплайн")
    seed_parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    seed_parser.add_argument(
        "--showcase",
        type=Path,
        default=None,
        help="Каталог витринных документов (отдельная коллекция)",
    )
    seed_parser.add_argument(
        "--with-users", action="store_true", help="Создать demo-пользователей из .env"
    )

    run_parser = sub.add_parser("run", help="Прогон evals на датасете")
    run_parser.add_argument("--dataset", default="golden")
    run_parser.add_argument("--dataset-path", type=Path, default=None)
    run_parser.add_argument("--judge", choices=["local", "cloud"], default=None)
    run_parser.add_argument("--limit", type=int, default=None)
    run_parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    run_parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    run_parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    run_parser.add_argument(
        "--reviewed-only",
        action="store_true",
        help="Только item'ы с reviewed:true (официальный гейт golden set)",
    )
    run_parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Перезаписать evals/baseline.json метриками этого run (только main)",
    )

    args = parser.parse_args()

    if args.command == "seed":
        print("Сид demo-корпуса:")
        counts = asyncio.run(seed_corpus(args.corpus))
        print(f"Корпус evals: {counts}")
        if args.showcase is not None:
            print("Сид витринных документов:")
            showcase_counts = asyncio.run(
                seed_corpus(
                    args.showcase,
                    collection_name=SHOWCASE_COLLECTION_NAME,
                    source_name="Витрина демо",
                )
            )
            print(f"Витрина: {showcase_counts}")
        if args.with_users:
            print("Demo-пользователи:")
            asyncio.run(seed_demo_users())
        return 0

    dataset_path = args.dataset_path or (
        DEFAULT_DATASET
        if args.dataset == "golden"
        else Path(f"evals/datasets/{args.dataset}.jsonl")
    )
    summary = asyncio.run(
        run_evals(
            dataset_name=args.dataset,
            dataset_path=dataset_path,
            thresholds_path=args.thresholds,
            baseline_path=args.baseline,
            output_dir=args.output,
            judge_provider=args.judge,
            limit=args.limit,
            reviewed_only=args.reviewed_only,
            update_baseline=args.update_baseline,
        )
    )
    print(f"Run {summary.run_id}: гейт {'ПРОЙДЕН' if summary.gate.passed else 'ПРОВАЛЕН'}")
    print(f"Отчёты: {summary.json_path} / {summary.md_path}")
    for metric, value in summary.aggregates.items():
        print(f"  {metric}: {value}")
    if not summary.gate.passed:
        for failure in summary.gate.failures:
            print(f"  ПРОВАЛ: {failure.metric} = {failure.value} ({failure.reason})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
