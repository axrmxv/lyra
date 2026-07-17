"""Нагрузочный смоук (фаза 7): факты p50/p95 против docs/nfr.md §1–2.

Сценарии (docs/nfr.md):
  search  — /search без rerank, целевой RPS и длительность параметрами
  rerank  — /search с rerank, последовательные запросы (CPU cross-encoder)
  chat    — N параллельных диалогов через SSE
  ingest  — пачка документов через /documents/upload

Запуск: python scripts/load_smoke.py search --rps 20 --duration 120
Результаты вписываются в docs/nfr-actual.md (расхождения — честно).
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
import uuid

import httpx

BASE = os.environ.get("LYRA_API_URL", "http://localhost:8000") + "/api/v1"

QUERIES = [
    "сколько дней отпуска",
    "как подключиться к vpn",
    "лимиты командировочных расходов",
    "тарифы для бизнеса",
    "sla поддержки клиентов",
    "как оформить закупку",
    "парольная политика",
    "окна деплоя",
]


def percentiles(samples: list[float]) -> str:
    if not samples:
        return "нет данных"
    ordered = sorted(samples)
    p50 = statistics.median(ordered)
    p95 = ordered[max(0, int(len(ordered) * 0.95) - 1)]
    return f"n={len(ordered)}, p50={p50:.0f} мс, p95={p95:.0f} мс, max={max(ordered):.0f} мс"


async def login(client: httpx.AsyncClient) -> None:
    response = await client.post(
        f"{BASE}/auth/login",
        json={
            "email": os.environ["LYRA_ADMIN_EMAIL"],
            "password": os.environ["LYRA_ADMIN_PASSWORD"],
        },
    )
    response.raise_for_status()
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"


async def scenario_search(rps: int, duration_s: int, rerank: bool) -> None:
    latencies: list[float] = []
    errors = 0

    async with httpx.AsyncClient(timeout=60) as client:
        await login(client)

        async def one(index: int) -> None:
            nonlocal errors
            started = time.monotonic()
            try:
                response = await client.post(
                    f"{BASE}/search",
                    json={"query": QUERIES[index % len(QUERIES)], "rerank": rerank},
                )
                response.raise_for_status()
                latencies.append((time.monotonic() - started) * 1000)
            except httpx.HTTPError:
                errors += 1

        if rerank:
            # CPU cross-encoder: последовательно, без целевого RPS
            deadline = time.monotonic() + duration_s
            index = 0
            while time.monotonic() < deadline:
                await one(index)
                index += 1
        else:
            tasks: list[asyncio.Task[None]] = []
            deadline = time.monotonic() + duration_s
            index = 0
            while time.monotonic() < deadline:
                tick = time.monotonic()
                for _ in range(rps):
                    tasks.append(asyncio.create_task(one(index)))
                    index += 1
                await asyncio.sleep(max(0.0, 1.0 - (time.monotonic() - tick)))
            await asyncio.gather(*tasks)

    label = "с rerank (последовательно)" if rerank else f"без rerank @ {rps} RPS"
    print(f"/search {label}, {duration_s}с: {percentiles(latencies)}, ошибок={errors}")


async def _chat_dialog(
    client: httpx.AsyncClient, dialog: int, latencies: list[float]
) -> None:
    session_id = (await client.post(f"{BASE}/chat/sessions")).json()["session_id"]
    question = QUERIES[dialog % len(QUERIES)]
    started = time.monotonic()
    async with client.stream(
        "POST",
        f"{BASE}/chat/sessions/{session_id}/messages",
        json={"content": question},
        timeout=900,
    ) as response:
        if response.status_code == 429:
            print(f"  диалог {dialog}: 429 (семафор LLM) — ожидаемо при перегрузе")
            return
        response.raise_for_status()
        buffer = ""
        async for chunk in response.aiter_text():
            buffer += chunk
            if "event: final" in buffer or "event: error" in buffer:
                break
    latencies.append((time.monotonic() - started) * 1000)
    print(f"  диалог {dialog}: {latencies[-1]:.0f} мс")


async def scenario_chat(parallel: int) -> None:
    latencies: list[float] = []
    async with httpx.AsyncClient(timeout=930) as client:
        await login(client)
        await asyncio.gather(
            *(_chat_dialog(client, i, latencies) for i in range(parallel))
        )
    print(f"chat x{parallel} параллельно: {percentiles(latencies)}")


async def scenario_ingest(count: int) -> None:
    async with httpx.AsyncClient(timeout=120) as client:
        await login(client)
        collection_id = (await client.get(f"{BASE}/sources")).json()["items"][0][
            "collection_id"
        ]
        marker = uuid.uuid4().hex[:6]
        job_ids: list[str] = []
        started = time.monotonic()
        for i in range(count):
            body = f"# Нагрузочный документ {marker}-{i}\n\nСодержимое {i}: {uuid.uuid4().hex}."
            response = await client.post(
                f"{BASE}/documents/upload",
                files={
                    "file": (f"load-{marker}-{i}.md", body.encode(), "text/markdown")
                },
                data={"collection_id": collection_id},
            )
            response.raise_for_status()
            job_ids.append(response.json()["job_id"])
        accepted_ms = (time.monotonic() - started) * 1000
        pending = set(job_ids)
        deadline = time.monotonic() + 600
        while pending and time.monotonic() < deadline:
            await asyncio.sleep(3)
            for job_id in list(pending):
                job = (await client.get(f"{BASE}/ingest/jobs/{job_id}")).json()
                if job["status"] in (
                    "completed",
                    "failed",
                    "failed_pii",
                    "skipped_duplicate",
                ):
                    pending.discard(job_id)
        total_s = time.monotonic() - started
    print(
        json.dumps(
            {
                "ingest_batch": count,
                "accept_ms": int(accepted_ms),
                "all_done_s": int(total_s),
                "undone": len(pending),
            },
            ensure_ascii=False,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="scenario", required=True)
    search = sub.add_parser("search")
    search.add_argument("--rps", type=int, default=20)
    search.add_argument("--duration", type=int, default=120)
    search.add_argument("--rerank", action="store_true")
    chat = sub.add_parser("chat")
    chat.add_argument("--parallel", type=int, default=3)
    ingest = sub.add_parser("ingest")
    ingest.add_argument("--count", type=int, default=20)
    args = parser.parse_args()

    if args.scenario == "search":
        asyncio.run(scenario_search(args.rps, args.duration, args.rerank))
    elif args.scenario == "chat":
        asyncio.run(scenario_chat(args.parallel))
    else:
        asyncio.run(scenario_ingest(args.count))
    return 0


if __name__ == "__main__":
    sys.exit(main())
