"""Проверки готовности зависимостей для GET /health/ready (docs/api-contract.md §7).

Каждая проверка — независимая корутина с коротким таймаутом; отказ одной
не мешает остальным (статусы собираются параллельно).
"""

import asyncio
from collections.abc import Awaitable, Callable

import asyncpg
import httpx
import redis.asyncio as aioredis

from lyra.core.config import Settings

CHECK_TIMEOUT_S = 3.0

DependencyCheck = Callable[[Settings], Awaitable[None]]


async def check_postgres(settings: Settings) -> None:
    conn = await asyncpg.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
        timeout=CHECK_TIMEOUT_S,
    )
    try:
        await conn.fetchval("SELECT 1")
    finally:
        await conn.close()


async def check_redis(settings: Settings) -> None:
    client = aioredis.from_url(settings.redis_url, socket_timeout=CHECK_TIMEOUT_S)
    try:
        await client.ping()
    finally:
        await client.aclose()


def _http_check(url_attr: str, path: str) -> DependencyCheck:
    async def check(settings: Settings) -> None:
        base_url: str = getattr(settings, url_attr)
        async with httpx.AsyncClient(timeout=CHECK_TIMEOUT_S) as client:
            response = await client.get(f"{base_url}{path}")
            response.raise_for_status()

    return check


CHECKS: dict[str, DependencyCheck] = {
    "postgres": check_postgres,
    "redis": check_redis,
    "ollama": _http_check("ollama_url", "/api/version"),
    "embeddings": _http_check("embeddings_url", "/health"),
    "reranker": _http_check("reranker_url", "/health"),
}


async def readiness_report(settings: Settings) -> dict[str, str]:
    """Статус каждой зависимости: up | down."""

    async def run_check(check: DependencyCheck) -> str:
        try:
            await asyncio.wait_for(check(settings), timeout=CHECK_TIMEOUT_S + 1)
        except Exception:
            return "down"
        return "up"

    names = list(CHECKS)
    results = await asyncio.gather(*(run_check(CHECKS[name]) for name in names))
    return dict(zip(names, results, strict=True))
