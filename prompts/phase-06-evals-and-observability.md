# Промпт фазы 6 — Evals с CI-гейтом и наблюдаемость

> Скопируй всё ниже в Claude Code. Предусловие: фазы 0–5 завершены (полный пайплайн вопрос→ответ работает).

---

Проект **LYRA** — RAG-платформа корпоративных знаний. В этой фазе качество становится измеримым и защищённым от регрессий. Прочитай перед началом: `docs/eval-plan.md` — главный документ фазы, реализуй его; `docs/PRD.md` §6 (пороги); `docs/data-model.md` (eval-таблицы); `docs/api-contract.md` §6; `docs/adr/ADR-009-llm-provider-abstraction.md` (judge — через тот же LLMClient).

## Что реализовать

### Evals (`lyra/evals/`, датасет и корпус — `evals/`)
1. **Демо-корпус** (`evals/corpus/`): 15–25 небольших документов на русском (markdown; вымышленная компания: политики HR, ИТ-инструкции, описания процессов, 2–3 дока с таблицами и код-блоками). Корпус — фикстура: версионируется в git, сидится командой.
2. **Golden dataset** (`evals/datasets/golden.jsonl`): **50+ items** по пропорциям `docs/eval-plan.md` §2 (40% single-chunk, 20% синтез, 10% таблицы/код, 15% paraphrase-пары, 15% unanswerable). Сгенерируй кандидатов по корпусу, затем помести итог как файл — я вручную отревьюирую (пометь поле `reviewed: false`, ревью — часть DoD). Схема item — eval_items из data-model.
3. **Judge-абстракция**: metrics-судья через LLMClient; конфиг выбирает локальную (qwen 14B) или облачную модель (env-ключ, только CI/offline — в runtime не используется); промпты judge — версионируемые файлы.
4. **Метрики** (по формулам `docs/eval-plan.md` §1): faithfulness (декомпозиция на утверждения → проверка против контекста), answer_relevance, context_precision (judge per-chunk), context_recall (детерминированно по expected_doc_ids/chunk_ids), citation_validity (детерминированная валидация + judge поддержки), honest_refusal_rate и false_refusal_rate (по kind=unanswerable/answerable). Вспомогательные: hit@k до/после rerank, corrective-rate, llm_calls, latency.
5. **Раннер**: CLI `python -m lyra.evals run --dataset golden [--judge cloud|local]` — прогон каждого item через настоящий граф (temperature=0), запись eval_runs/eval_records + `config_snapshot` (git_ref, версии промптов, модели, retrieval-параметры, chunking_config), JSON+markdown отчёт с worst items; Celery-задача (очередь evals) + `POST/GET /admin/eval-runs` по api-contract §6; сравнение с baseline (последний успешный run на main — файл-артефакт `evals/baseline.json`).
6. **Гейт CI**: `evals/thresholds.yaml` (значения из PRD §6); GitHub Actions job (path-фильтр: промпты, retrieval, chunking, конфиги моделей; + nightly полный): поднимает compose, сидит корпус, гоняет evals, красный при пороге ИЛИ падении > 0.05 от baseline; markdown-отчёт с дельтами — комментарием в PR.

### Наблюдаемость
7. **Метрики Prometheus** (дозаполнить): гистограммы по узлам графа и этапам retrieval/ingest, счётчики refusal/corrective/self_check_retry/degraded, gauge размера индекса, токены по узлам (FR-20).
8. **Grafana** (`infra/grafana/provisioning/`): дашборд из JSON в репозитории: latency-разбивка запроса по этапам, RPS, доля отказов, очередь ingest, токены/запрос.
9. **LLM-трейсы**: убедиться, что каждый вызов пишет trace_id/узел/токены/длительность (обёртка фазы 4); endpoint-путь просмотра — по trace_id в структурных логах (docker logs + jq рецепт в README); трейсы наружу не отправляются (`docs/security-and-access.md` §5).

## Критерии приёмки
- `make eval` на чистом стенде: run завершён, все гейт-метрики посчитаны, отчёт сгенерирован; повторный прогон — метрики стабильны (±0.05).
- Намеренная порча: убрать из system-промпта требование «только по источникам» → faithfulness/citation validity падают, CI-job красный. Вернуть → зелёный.
- Grafana показывает разбивку живого chat-запроса по этапам.
- В отчёте run'а видны: baseline-дельты, worst-5 items с trace_id.

## Тесты
- Юнит: context_recall (детерминированный) на синтетике; citation_validity-валидатор; расчёт агрегатов и сравнение с baseline; парсер thresholds.
- Интеграционный: мини-датасет (3 item) с FakeLLM-judge — конвейер run→records→отчёт.
