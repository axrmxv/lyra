"""Смоук-прогон UC-1..UC-9 через API (фаза 7): приёмка и регресс перед показом.

Запуск (стенд поднят, seed-demo выполнен):
    python scripts/demo_smoke.py            # UC-8 (eval-run) — SKIP
    DEMO_SMOKE_EVAL=1 python scripts/demo_smoke.py   # с запуском eval-run

Креды admin — из env LYRA_ADMIN_EMAIL / LYRA_ADMIN_PASSWORD (как в .env).
На CPU-стенде полный прогон занимает 10–20 минут (LLM-ответы по минутам).
"""

import json
import os
import sys
import time
import uuid

import httpx

BASE = os.environ.get("LYRA_API_URL", "http://localhost:8000") + "/api/v1"
RUN_EVAL = os.environ.get("DEMO_SMOKE_EVAL") == "1"

results: list[tuple[str, str, str, str]] = []  # (uc, название, статус, детали)


def record(uc: str, title: str, status: str, details: str = "") -> None:
    results.append((uc, title, status, details))
    print(f"  {uc}: {status} {details}", flush=True)


def sse_final(client: httpx.Client, session_id: str, content: str) -> dict:
    """Отправка вопроса; возвращает data события final (или error → исключение)."""
    with client.stream(
        "POST",
        f"{BASE}/chat/sessions/{session_id}/messages",
        json={"content": content},
        timeout=900,
    ) as response:
        response.raise_for_status()
        buffer = ""
        for chunk in response.iter_text():
            buffer += chunk
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                name, data = None, None
                for line in block.split("\n"):
                    if line.startswith("event: "):
                        name = line[7:]
                    elif line.startswith("data: "):
                        data = line[6:]
                if name == "final" and data:
                    return json.loads(data)
                if name == "error" and data:
                    raise RuntimeError(f"SSE error: {data}")
    raise RuntimeError("final не получен")


def wait_job(client: httpx.Client, job_id: str, timeout_s: int = 300) -> str:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        job = client.get(f"{BASE}/ingest/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed", "failed_pii", "skipped_duplicate"):
            return str(job["status"])
        time.sleep(3)
    return "timeout"


def main() -> int:
    email = os.environ["LYRA_ADMIN_EMAIL"]
    password = os.environ["LYRA_ADMIN_PASSWORD"]
    client = httpx.Client(timeout=60)
    login = client.post(
        f"{BASE}/auth/login", json={"email": email, "password": password}
    )
    login.raise_for_status()
    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    print("Логин ок. Прогон UC-1..UC-9:", flush=True)

    session_id = client.post(f"{BASE}/chat/sessions").json()["session_id"]

    # UC-1: ответ с цитатами
    try:
        final = sse_final(
            client, session_id, "Какие тарифы подключения есть для бизнеса?"
        )
        assert not final["refusal"] and final["citations"], final
        assert "[1]" in final["answer"]
        record(
            "UC-1",
            "Вопрос-ответ с цитатами",
            "PASS",
            f"citations={len(final['citations'])}",
        )
    except Exception as exc:
        record("UC-1", "Вопрос-ответ с цитатами", "FAIL", str(exc)[:120])

    # UC-2: честный отказ — отдельная сессия (negative-вопрос без истории;
    # в диалоге condense пытается связать вопрос с темой — известный хвост)
    try:
        clean_session = client.post(f"{BASE}/chat/sessions").json()["session_id"]
        final = sse_final(
            client, clean_session, "Какой размер годового бонуса сотрудника?"
        )
        assert final[
            "refusal"
        ], f"ожидался отказ, получен ответ: {final['answer'][:80]}"
        record(
            "UC-2",
            "Честный отказ",
            "PASS",
            f"nearest={len(final['nearest_documents'])}",
        )
    except Exception as exc:
        record("UC-2", "Честный отказ", "FAIL", str(exc)[:120])

    # UC-3: follow-up с учётом истории
    try:
        final = sse_final(client, session_id, "А какой SLA у самого дорогого из них?")
        history = client.get(f"{BASE}/chat/sessions/{session_id}/messages").json()
        # В основной сессии UC-1 + UC-3 (UC-2 идёт в отдельной чистой сессии)
        assert history["total"] >= 4, f"сообщений: {history['total']}"
        record(
            "UC-3",
            "Уточняющий диалог",
            "PASS",
            f"refusal={final['refusal']}, сообщений={history['total']}",
        )
    except Exception as exc:
        record("UC-3", "Уточняющий диалог", "FAIL", str(exc)[:120])

    # Коллекция для загрузок — из sources
    collection_id = client.get(f"{BASE}/sources").json()["items"][0]["collection_id"]

    # UC-4: загрузка документа → индексация → поиск
    marker = uuid.uuid4().hex[:6]
    doc_name = f"smoke-{marker}.md"
    doc_body = (
        f"# Регламент смоук-теста {marker}\n\n"
        f"Кодовое слово прогона: астролябия-{marker}. "
        "Документ создан автоматически для проверки UC-4/UC-6."
    ).encode()
    document_id = ""
    try:
        upload = client.post(
            f"{BASE}/documents/upload",
            files={"file": (doc_name, doc_body, "text/markdown")},
            data={"collection_id": collection_id},
        )
        assert upload.status_code == 202, upload.text
        document_id = upload.json()["document_id"]
        status = wait_job(client, upload.json()["job_id"])
        assert status == "completed", f"job={status}"
        search = client.post(
            f"{BASE}/search",
            json={"query": f"кодовое слово астролябия {marker}", "rerank": False},
        ).json()
        found_ids = [r["document"]["id"] for r in search["results"]]
        assert document_id in found_ids, f"документ не в выдаче ({len(found_ids)} рез.)"
        record("UC-4", "Загрузка документов", "PASS", f"job={status}, найден поиском")
    except Exception as exc:
        record("UC-4", "Загрузка документов", "FAIL", str(exc)[:120])

    # UC-5: Confluence-коннектор (API-поверхность; живой space не требуется)
    try:
        source = client.post(
            f"{BASE}/sources",
            json={
                "collection_id": collection_id,
                "type": "confluence",
                "name": f"smoke-confluence-{marker}",
                "config": {
                    "base_url": "https://example.atlassian.net/wiki",
                    "spaces": ["DEMO"],
                    "token_secret_ref": "CONFLUENCE_TOKEN",
                },
            },
        )
        assert source.status_code == 201, source.text
        source_id = source.json()["id"]
        sync = client.post(f"{BASE}/sources/{source_id}/sync")
        assert sync.status_code == 202, sync.text
        client.delete(f"{BASE}/sources/{source_id}")
        record(
            "UC-5", "Подключение Confluence", "PASS", "API-поверхность (sync поставлен)"
        )
    except Exception as exc:
        record("UC-5", "Подключение Confluence", "FAIL", str(exc)[:120])

    # UC-6: идемпотентность и версии
    try:
        dup = client.post(
            f"{BASE}/documents/upload",
            files={"file": (doc_name, doc_body, "text/markdown")},
            data={"collection_id": collection_id},
        )
        dup_status = wait_job(client, dup.json()["job_id"])
        assert dup_status == "skipped_duplicate", f"дубликат: {dup_status}"
        updated = client.post(
            f"{BASE}/documents/upload",
            files={
                "file": (
                    doc_name,
                    doc_body + "\n\nОбновлено.".encode(),
                    "text/markdown",
                )
            },
            data={"collection_id": collection_id},
        )
        upd_status = wait_job(client, updated.json()["job_id"])
        assert upd_status == "completed", f"новая версия: {upd_status}"
        detail = client.get(f"{BASE}/documents/{document_id}").json()
        active = [v for v in detail["versions"] if v["status"] == "active"]
        assert len(active) == 1 and len(detail["versions"]) == 2
        record(
            "UC-6", "Обновление документа", "PASS", "dup=skipped, версий=2, active=1"
        )
    except Exception as exc:
        record("UC-6", "Обновление документа", "FAIL", str(exc)[:120])

    # UC-7: фидбек
    try:
        messages = client.get(f"{BASE}/chat/sessions/{session_id}/messages").json()[
            "items"
        ]
        answer_id = next(m["id"] for m in messages if m["role"] == "assistant")
        feedback = client.post(
            f"{BASE}/feedback",
            json={
                "message_id": answer_id,
                "rating": "down",
                "comment": f"smoke-{marker}",
            },
        )
        assert feedback.status_code == 201, feedback.text
        listing = client.get(f"{BASE}/feedback", params={"rating": "down"}).json()
        assert any(item["comment"] == f"smoke-{marker}" for item in listing["items"])
        record("UC-7", "Фидбек", "PASS")
    except Exception as exc:
        record("UC-7", "Фидбек", "FAIL", str(exc)[:120])

    # UC-8: запуск evals (тяжёлый — по флагу; иначе проверка поверхности)
    try:
        missing = client.get(f"{BASE}/admin/eval-runs/{uuid.uuid4()}")
        assert missing.status_code == 404
        if RUN_EVAL:
            accepted = client.post(
                f"{BASE}/admin/eval-runs", json={"dataset_name": "golden"}
            )
            assert accepted.status_code == 202, accepted.text
            record(
                "UC-8",
                "Запуск evals",
                "PASS",
                f"run={accepted.json()['run_id']} (в очереди)",
            )
        else:
            record(
                "UC-8",
                "Запуск evals",
                "SKIP",
                "полный прогон — make eval / DEMO_SMOKE_EVAL=1",
            )
    except Exception as exc:
        record("UC-8", "Запуск evals", "FAIL", str(exc)[:120])

    # UC-9: прямой поиск
    try:
        started = time.monotonic()
        search = client.post(
            f"{BASE}/search", json={"query": "сколько дней отпуска", "rerank": True}
        ).json()
        took = int((time.monotonic() - started) * 1000)
        assert search["results"], "пустая выдача"
        record(
            "UC-9",
            "Прямой поиск",
            "PASS",
            f"{len(search['results'])} результатов, {took} мс",
        )
    except Exception as exc:
        record("UC-9", "Прямой поиск", "FAIL", str(exc)[:120])

    print("\n| UC | Сценарий | Статус | Детали |")
    print("|----|----------|--------|--------|")
    for uc, title, status, details in results:
        print(f"| {uc} | {title} | {status} | {details} |")

    failed = [r for r in results if r[2] == "FAIL"]
    print(f"\nИтог: {len(results) - len(failed)}/{len(results)} PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
