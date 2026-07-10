---
description: Разобрать трейс одного RAG-запроса по trace_id
---

Разбери прохождение запроса через RAG-граф. Вход: $ARGUMENTS (trace_id, например tr_01H..., либо текст вопроса — тогда сначала найди его trace_id в последних логах).

0. Предусловие: команда работает начиная с фазы 4 (`PLAN.md` — граф и трейсинг созданы). Если `infra/docker-compose.yml` или пакет `lyra/rag/` ещё не существуют — сообщи об этом и остановись.
1. Достань все записи трейса: `docker compose -f infra/docker-compose.yml logs api worker | grep <trace_id>` (структурные JSON-логи; распарси jq-ом при необходимости). Если есть запись в `messages` — возьми также `graph_meta`.
2. Восстанови траекторию по узлам (`docs/adr/ADR-006-langgraph-topology.md`): condense → retrieve → grade_sufficiency → [corrective]* → generate → cite → self_check → answer/refusal.
3. Выведи разбор:
   - таблица узлов по порядку: узел, модель, prompt/completion tokens, длительность, вердикт (для grade/self_check);
   - retrieval: сколько кандидатов из BM25/вектора, топ после RRF и после rerank (id, score, документ), был ли degraded;
   - сработавшие ветки: число corrective-итераций и переписанные запросы, retry генерации, причина refusal (если был);
   - итог: confidence и его составляющие, citations и их валидность;
   - сумма: llm_calls, токены, полная латентность vs бюджет `docs/nfr.md` §1.
4. Диагноз: где запрос «потерял качество» или время (плохой retrieval? ошибочный grading? усечение контекста `context_truncated`? медленный узел?). Дай 1–3 конкретные гипотезы с указанием на конфиг/промпт/данные — но не меняй ничего без моего подтверждения.
