"""События RAG-графа наружу — контракт SSE chat-API (api-contract §4).

Узлы остаются чистыми: sink внедряется через GraphDeps, статусы эмитит
обвязка графа (build_graph), токены — узел generate. Стадии — строго
перечень контракта: retrieving | grading | corrective_retrieve |
generating | self_check.
"""

from typing import Protocol


class EventSink(Protocol):
    async def emit_status(self, stage: str) -> None: ...

    async def emit_token(self, text: str) -> None: ...


class NullSink:
    """По умолчанию граф молчит — evals и не-SSE-вызовы событий не требуют."""

    async def emit_status(self, stage: str) -> None:
        return None

    async def emit_token(self, text: str) -> None:
        return None
