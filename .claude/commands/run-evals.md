---
description: Прогнать offline-evals и сравнить с baseline
---

Прогони eval-контур и разбери результат:

0. Предусловие: команда работает начиная с фазы 6 (`PLAN.md`). Если `Makefile` или `evals/thresholds.yaml` ещё не существуют — сообщи, что eval-контур появится в фазе 6, и остановись.
1. Убедись, что стек поднят (`docker compose -f infra/docker-compose.yml ps`); если нет — `make up` и дождись healthy.
2. Убедись, что демо-корпус посеян (в БД есть chunks); если нет — `make seed-demo`.
3. Запусти: `make eval` (эквивалент `python -m lyra.evals run --dataset golden`). Аргумент команды `$ARGUMENTS`, если передан, — имя датасета или `--judge cloud|local`.
4. Открой сгенерированный отчёт run'а и выведи мне:
   - таблицу метрик против порогов из `evals/thresholds.yaml` (PASS/FAIL по каждой);
   - дельты против baseline (`evals/baseline.json`) с пометкой регрессий > 0.05;
   - worst-5 items: вопрос, провалившаяся метрика, trace_id.
5. Если есть FAIL или регрессия: по каждому worst item найди трейс в логах по trace_id и сформулируй гипотезу — retrieval не нашёл (смотри context_recall и retrieved chunks), grading ошибся, генерация ушла от контекста или судья шумит. НЕ предлагай менять пороги (`.claude/rules/evals.md`).
6. Если всё зелёное и это ветка с изменениями промптов/retrieval — предложи обновить baseline отдельным коммитом.
