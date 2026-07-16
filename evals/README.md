# Eval-контур LYRA

Оффлайн-оценка качества RAG-пайплайна: демо-корпус, golden dataset,
метрики (`docs/eval-plan.md`), пороги CI-гейта.

## Структура

- `corpus/` — демо-корпус вымышленной компании «Астра-Линк» (markdown, ru).
  **Фикстура**: версионируется в git, меняется только вместе с пересмотром
  датасета и baseline (`.claude/rules/evals.md`). Политики компании
  намеренно отличаются от типовых (например, отпуск 31 день, а не 28) —
  это ловит подмену контекста «общими знаниями» модели (eval-plan §5).
- `datasets/golden.jsonl` — golden dataset; append-only, синтетика без
  `reviewed: true` в гейте не участвует.
- `thresholds.yaml` — пороги CI-гейта (менять только отдельным PR
  с обоснованием).
- `baseline.json` — агрегаты последнего успешного run на main.

## Команды

```bash
# Сид корпуса в чистый стенд (через ingest-пайплайн, идемпотентно)
python -m lyra.evals seed --corpus evals/corpus

# Прогон evals
python -m lyra.evals run --dataset golden --judge local
make eval   # обёртка с дефолтами
```
