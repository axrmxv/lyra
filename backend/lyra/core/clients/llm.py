"""LLMClient — единственная точка LLM-вызовов (ADR-009).

Прямые вызовы Ollama/SDK по коду запрещены (инвариант 5 CLAUDE.md):
каждый вызов проходит трейсинг здесь — structlog-запись (узел, модель,
токены, длительность, trace_id из contextvars) + Prometheus.

structured(): Ollama JSON-schema-режим + валидация Pydantic + 1 retry
c сообщением об ошибке — рабочая лошадка grading/self_check/rewrite.
"""

import json
import time
from collections.abc import AsyncIterator, Callable
from typing import Any, Protocol, TypeVar

import httpx
import structlog
from pydantic import BaseModel, ValidationError

from lyra.core.metrics import LLM_CALL_SECONDS, LLM_TOKENS

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

Message = dict[str, str]  # {"role": "system|user|assistant", "content": ...}


class LLMResult(BaseModel):
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMUnavailable(Exception):
    """Ollama недоступен/таймаут — честная 503 наверху (architecture.md §4)."""


class LLMFormatError(Exception):
    """Модель не выдала валидный structured-ответ после retry."""


class LLMClient(Protocol):
    async def chat(
        self,
        messages: list[Message],
        *,
        node: str,
        model_role: str = "generation",
        max_tokens: int | None = None,
    ) -> LLMResult: ...

    def chat_stream(
        self,
        messages: list[Message],
        *,
        node: str,
        model_role: str = "generation",
        max_tokens: int | None = None,
        on_usage: Callable[[int, int], None] | None = None,
    ) -> AsyncIterator[str]: ...

    async def structured(
        self,
        messages: list[Message],
        schema: type[T],
        *,
        node: str,
        model_role: str = "grading",
    ) -> tuple[T, LLMResult]: ...


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        *,
        generation_model: str,
        grading_model: str,
        timeout_s: float = 120.0,
        num_ctx: int = 16384,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._models = {"generation": generation_model, "grading": grading_model}
        self._timeout_s = timeout_s
        self._num_ctx = num_ctx

    def _model(self, role: str) -> str:
        return self._models.get(role, self._models["generation"])

    def _trace(self, node: str, model: str, result: LLMResult, started: float) -> None:
        duration = time.monotonic() - started
        LLM_CALL_SECONDS.labels(node=node, model=model).observe(duration)
        LLM_TOKENS.labels(node=node, direction="prompt").inc(result.prompt_tokens)
        LLM_TOKENS.labels(node=node, direction="completion").inc(result.completion_tokens)
        logger.info(
            "llm_call",
            node=node,
            model=model,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            duration_ms=int(duration * 1000),
        )

    async def _chat_raw(
        self,
        messages: list[Message],
        model: str,
        *,
        fmt: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0, "num_ctx": self._num_ctx},
        }
        if max_tokens is not None:
            payload["options"]["num_predict"] = max_tokens
        if fmt is not None:
            payload["format"] = fmt
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                response = await client.post(f"{self._base_url}/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMUnavailable(f"{type(exc).__name__}: {exc}") from exc
        return LLMResult(
            text=data.get("message", {}).get("content", ""),
            prompt_tokens=int(data.get("prompt_eval_count", 0)),
            completion_tokens=int(data.get("eval_count", 0)),
        )

    async def chat(
        self,
        messages: list[Message],
        *,
        node: str,
        model_role: str = "generation",
        max_tokens: int | None = None,
    ) -> LLMResult:
        model = self._model(model_role)
        started = time.monotonic()
        result = await self._chat_raw(messages, model, max_tokens=max_tokens)
        self._trace(node, model, result, started)
        return result

    async def chat_stream(
        self,
        messages: list[Message],
        *,
        node: str,
        model_role: str = "generation",
        max_tokens: int | None = None,
        on_usage: Callable[[int, int], None] | None = None,
    ) -> AsyncIterator[str]:
        """Стрим токенов; финальный chunk Ollama несёт счётчики — трейсим по done."""
        model = self._model(model_role)
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": 0, "num_ctx": self._num_ctx},
        }
        if max_tokens is not None:
            payload["options"]["num_predict"] = max_tokens
        started = time.monotonic()
        prompt_tokens = completion_tokens = 0
        collected: list[str] = []
        try:
            async with (
                httpx.AsyncClient(timeout=self._timeout_s) as client,
                client.stream("POST", f"{self._base_url}/api/chat", json=payload) as response,
            ):
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    piece = chunk.get("message", {}).get("content", "")
                    if piece:
                        collected.append(piece)
                        yield piece
                    if chunk.get("done"):
                        prompt_tokens = int(chunk.get("prompt_eval_count", 0))
                        completion_tokens = int(chunk.get("eval_count", 0))
                        if on_usage is not None:
                            on_usage(prompt_tokens, completion_tokens)
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMUnavailable(f"{type(exc).__name__}: {exc}") from exc
        finally:
            self._trace(
                node,
                model,
                LLMResult(
                    text="".join(collected),
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                ),
                started,
            )

    async def structured(
        self,
        messages: list[Message],
        schema: type[T],
        *,
        node: str,
        model_role: str = "grading",
    ) -> tuple[T, LLMResult]:
        """(разобранный объект, суммарный usage — включая retry)."""
        model = self._model(model_role)
        fmt = schema.model_json_schema()
        started = time.monotonic()
        result = await self._chat_raw(messages, model, fmt=fmt)
        self._trace(node, model, result, started)
        try:
            return schema.model_validate_json(result.text), result
        except ValidationError as first_error:
            retry_messages = [
                *messages,
                {"role": "assistant", "content": result.text},
                {
                    "role": "user",
                    "content": (
                        "Ответ не прошёл валидацию схемы: "
                        f"{first_error.error_count()} ошибок. Верни СТРОГО валидный JSON "
                        "по заданной схеме, без пояснений."
                    ),
                },
            ]
            started_retry = time.monotonic()
            retry = await self._chat_raw(retry_messages, model, fmt=fmt)
            self._trace(f"{node}_retry", model, retry, started_retry)
            combined = LLMResult(
                text=retry.text,
                prompt_tokens=result.prompt_tokens + retry.prompt_tokens,
                completion_tokens=result.completion_tokens + retry.completion_tokens,
            )
            try:
                return schema.model_validate_json(retry.text), combined
            except ValidationError as exc:
                raise LLMFormatError(f"Невалидный structured-ответ узла {node}") from exc
