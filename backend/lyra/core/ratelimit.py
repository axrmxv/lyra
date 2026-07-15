"""Rate limiting per-user/per-IP на Redis (security-and-access §7, nfr §2).

Fixed window: INCR + EXPIRE на первом хите окна. Точность окна достаточна
для защиты локальной LLM от случайного DoS; скользящее окно — production.

Fail-open: недоступный Redis не роняет запросы (лимитер — защита от
перегрузки, не security-контроль), но пишет warning в лог.
"""

import asyncio
from dataclasses import dataclass
from functools import lru_cache
from weakref import WeakKeyDictionary

import redis.asyncio as aioredis
import structlog

from lyra.core.config import get_settings

logger = structlog.get_logger(__name__)

WINDOW_S = 60


@dataclass
class RateDecision:
    allowed: bool
    retry_after_s: int = 0


class RateLimiter:
    """Клиент Redis создаётся per event loop: соединение, привязанное к
    закрытому loop (тесты, перезапуск), нельзя переиспользовать."""

    def __init__(self, redis_url: str) -> None:
        self._url = redis_url
        self._clients: WeakKeyDictionary[asyncio.AbstractEventLoop, aioredis.Redis] = (
            WeakKeyDictionary()
        )

    def _client(self) -> "aioredis.Redis":
        loop = asyncio.get_running_loop()
        client = self._clients.get(loop)
        if client is None:
            client = aioredis.Redis.from_url(self._url)
            self._clients[loop] = client
        return client

    async def hit(self, key: str, limit: int, window_s: int = WINDOW_S) -> RateDecision:
        try:
            client = self._client()
            count = await client.incr(key)
            if count == 1:
                await client.expire(key, window_s)
            if count <= limit:
                return RateDecision(allowed=True)
            ttl = await client.ttl(key)
            return RateDecision(allowed=False, retry_after_s=max(int(ttl), 1))
        except (TimeoutError, aioredis.RedisError, OSError) as exc:
            logger.warning("rate_limiter_unavailable", key=key, error=str(exc))
            return RateDecision(allowed=True)


@lru_cache
def get_rate_limiter() -> RateLimiter:
    return RateLimiter(get_settings().redis_url)
