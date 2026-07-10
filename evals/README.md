# Evals

Контур оценки качества (docs/eval-plan.md). Наполняется в фазе 6:

- `corpus/` — демо-корпус (фикстура, версионируется вместе с датасетом)
- `datasets/golden.jsonl` — golden dataset (append-only)
- `thresholds.yaml` — пороги CI-гейта (не менять без обоснования — .claude/rules/evals.md)
- `baseline.json` — метрики последнего успешного run на main
