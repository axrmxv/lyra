"""Фейки для тестов RAG-графа: FakeLLM (сценарии по узлам) и FakeRetriever.

Не тестовый модуль — общие фикстуры-компоненты (импортируется тестами).
"""

import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any, TypeVar

from pydantic import BaseModel

from lyra.core.clients.llm import LLMResult, Message
from lyra.retrieval.interfaces import RetrievalResult, ScoredChunk

T = TypeVar("T", bound=BaseModel)


def make_chunk(
    text: str,
    *,
    ordinal: int = 0,
    rerank: float | None = 0.5,
    title: str = "Документ",
    tokens: int = 50,
) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        ordinal=ordinal,
        text=text,
        token_count=tokens,
        meta={"doc_title": title, "url": f"http://kb/{title}", "lang": "ru"},
        rrf_score=0.03,
        rerank_score=rerank,
    )


class FakeLLM:
    """Ответы по имени узла: chat_responses[node] — очередь строк,
    structured_responses[node] — очередь объектов схемы."""

    def __init__(
        self,
        chat_responses: dict[str, list[str]] | None = None,
        structured_responses: dict[str, list[BaseModel]] | None = None,
    ) -> None:
        self.chat_responses = chat_responses or {}
        self.structured_responses = structured_responses or {}
        self.calls: list[str] = []  # хронология узлов — проверка траектории

    def _pop(self, mapping: dict[str, list[Any]], node: str) -> Any:
        queue = mapping.get(node)
        if not queue:
            raise AssertionError(f"FakeLLM: нет сценария для узла {node}")
        return queue.pop(0)

    async def chat(
        self,
        messages: list[Message],
        *,
        node: str,
        model_role: str = "generation",
        max_tokens: int | None = None,
    ) -> LLMResult:
        self.calls.append(node)
        return LLMResult(
            text=self._pop(self.chat_responses, node), prompt_tokens=10, completion_tokens=5
        )

    async def chat_stream(
        self,
        messages: list[Message],
        *,
        node: str,
        model_role: str = "generation",
        max_tokens: int | None = None,
        on_usage: Callable[[int, int], None] | None = None,
    ) -> AsyncIterator[str]:
        self.calls.append(node)
        text = self._pop(self.chat_responses, node)
        for piece in text.split(" "):
            yield piece + " "
        if on_usage is not None:
            on_usage(100, 20)

    async def structured(
        self,
        messages: list[Message],
        schema: type[T],
        *,
        node: str,
        model_role: str = "grading",
    ) -> tuple[T, LLMResult]:
        self.calls.append(node)
        obj = self._pop(self.structured_responses, node)
        assert isinstance(obj, schema)
        return obj, LLMResult(text="{}", prompt_tokens=10, completion_tokens=5)


class FakeRetriever:
    """Очередь результатов: каждый вызов retrieve отдаёт следующий список chunks."""

    def __init__(self, batches: list[list[ScoredChunk]], degraded: bool = False) -> None:
        self.batches = batches
        self.degraded = degraded
        self.queries: list[str] = []

    async def retrieve(self, query: str, **kwargs: Any) -> RetrievalResult:
        self.queries.append(query)
        chunks = self.batches.pop(0) if self.batches else []
        return RetrievalResult(chunks=chunks, degraded=self.degraded, took_ms=5)
