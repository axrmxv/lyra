"""Очередь к локальной LLM: семафор одновременных генераций (nfr §2).

Ollama на CPU-стенде обслуживает 1-2 генерации; всё сверх лимита получает
честный 429 сразу, а не копит хвост таймаутов.
"""

import asyncio
from functools import lru_cache

from lyra.core.config import get_settings


class GenerationGate:
    def __init__(self, limit: int) -> None:
        self._sem = asyncio.Semaphore(limit)

    async def try_acquire(self) -> bool:
        """Слот без ожидания: занято → False (наверху — 429).

        Event loop однопоточный: между locked() и acquire() нет await,
        поэтому acquire гарантированно идёт по fast-path без подвисания.
        """
        if self._sem.locked():
            return False
        await self._sem.acquire()
        return True

    def release(self) -> None:
        self._sem.release()


@lru_cache
def get_generation_gate() -> GenerationGate:
    return GenerationGate(get_settings().llm_max_concurrency)
