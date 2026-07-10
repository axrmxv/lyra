# Промпт фазы 5 — Chat API (SSE) и React UI

> Скопируй всё ниже в Claude Code. Предусловие: фазы 0–4 завершены (RAG-граф отвечает).

---

Проект **LYRA** — RAG-платформа корпоративных знаний. В этой фазе система становится продуктом: чат со стримингом, цитатами-сносками, фидбеком и экранами управления. Прочитай перед началом: `docs/api-contract.md` §4–5 (контракт SSE — реализуй байт-в-байт), `docs/PRD.md` (UC-1..UC-7), `docs/adr/ADR-007-citation-strategy.md` (§4 — рендер цитат), `docs/security-and-access.md` §7 (rate limiting, CORS).

## Что реализовать

### Backend (`lyra/api/routes/`)
1. **Chat**: `POST /chat/sessions`, `GET /chat/sessions`, `GET /chat/sessions/{id}/messages`, `POST /chat/sessions/{id}/messages` — SSE-стрим строго по api-contract §4: события `status` (стадии графа — подписка на переходы узлов), `token`, `final` (полный payload: answer, refusal, citations, confidence, degraded, trace_id, usage, nearest_documents при отказе), `error`. Сообщения и citations персистятся (messages, message_citations из `docs/data-model.md`); graph_meta — вердикты/итерации для отладки. Доступ только к своим сессиям.
2. **Feedback**: `POST /feedback` (viewer, привязка к message_id), `GET /feedback` (admin, фильтры) — api-contract §5.
3. **Rate limiting** (Redis, per-user): /chat — например 10/мин, /auth/login — 5/мин; 429 с Retry-After (`docs/nfr.md` §2 — защита локальной LLM).
4. Очередь к Ollama: семафор одновременных генераций (конфиг, дефолт 2); переполнение → 429.

### Frontend (`frontend/src/`)
5. **Каркас**: роутер (login, chat, documents, sources/jobs), auth-контекст (JWT в памяти + localStorage refresh поведения нет — просто relogin), API-клиент с типами из контракта (сгенерируй TS-типы вручную по api-contract, вынеси в `src/api/types.ts`).
6. **Чат** (главный экран): список сессий; поток сообщений; при отправке — SSE (fetch + ReadableStream): индикатор стадий из `status`-событий («ищу источники → проверяю достаточность → отвечаю»), инкрементальный рендер токенов; маркеры `[n]` рендерятся сносками-чипами → popover: document_title, quote, relevance, ссылка url; confidence-бейдж (high/medium/low + score) у ответа; refusal-состояние — отдельный стиль + список nearest_documents; degraded — ненавязчивый warning; кнопки 👍/👎 + комментарий (POST /feedback).
7. **Документы и загрузка**: drag-n-drop upload (валидация типа/размера на клиенте), список jobs со статусами (поллинг GET /ingest/jobs), список документов, страница sources (для editor: создание Confluence-source, кнопка sync).
8. **UX-минимум**: русский интерфейс; ошибки API → понятные тосты; тёмная/светлая тема не обязательна.

## Критерии приёмки (ручной прогон end-to-end)
- UC-1: вопрос → стриминг → ответ со сносками; клик по сноске → popover с цитатой и рабочей ссылкой.
- UC-2: вопрос вне корпуса → отказ + ближайшие документы.
- UC-3: follow-up («а сколько во второй год?») учитывает контекст диалога.
- UC-4: drag-n-drop PDF → job виден, по завершении документ находится в чате.
- UC-7: 👎 с комментарием сохраняется, admin видит в GET /feedback.
- SSE-события соответствуют api-contract §4 (проверь curl'ом последовательность status → token* → final).

## Тесты
- pytest: SSE-эндпоинт с FakeLLM — порядок событий, структура final, персистенция message+citations, доступ к чужой сессии → 403, rate limit → 429.
- Vitest (+ testing-library): рендер маркеров [n] в сноски (включая маркер без citation — не падать), refusal-состояние, confidence-бейдж, редьюсер SSE-потока (status/token/final/error), форма фидбека.
