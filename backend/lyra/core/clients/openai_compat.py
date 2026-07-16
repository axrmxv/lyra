"""OpenAI-совместимый LLM-клиент (ADR-009) — облачный judge для evals/CI.

Реализует тот же Protocol LLMClient, что и OllamaClient: все вызовы
трейсятся. В runtime-путях не используется (eval-plan §1: judge только
offline). Совместим с любым /chat/completions-endpoint (OpenAI,
OpenRouter, DeepSeek и т.п.).
"""

import json
import time
from collections.abc import AsyncIterator, Callable
from typing import Any, TypeVar

import httpx
import structlog
from pydantic import BaseModel, ValidationError

from lyra.core.clients.llm import LLMFormatError, LLMResult, LLMUnavailable, Message
from lyra.core.metrics import LLM_CALL_SECONDS, LLM_TOKENS

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


class OpenAICompatClient:
    def __init__(
        self,
        base_url: str,
        *,
        api_key: str,
        model: str,
        timeout_s: float = 120.0,
    ) -> None:
        if not base_url or not api_key:
            raise ValueError("Для облачного judge нужны judge_api_base и judge_api_key")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout_s = timeout_s

    def _trace(self, node: str, result: LLMResult, started: float) -> None:
        duration = time.monotonic() - started
        LLM_CALL_SECONDS.labels(node=node, model=self._model).observe(duration)
        LLM_TOKENS.labels(node=node, direction="prompt").inc(result.prompt_tokens)
        LLM_TOKENS.labels(node=node, direction="completion").inc(result.completion_tokens)
        logger.info(
            "llm_call",
            node=node,
            model=self._model,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            duration_ms=int(duration * 1000),
        )

    async def _chat_raw(
        self,
        messages: list[Message],
        *,
        json_mode: bool = False,
        max_tokens: int | None = None,
    ) -> LLMResult:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": 0,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMUnavailable(f"{type(exc).__name__}: {exc}") from exc
        usage = data.get("usage") or {}
        return LLMResult(
            text=data["choices"][0]["message"]["content"] or "",
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
        )

    async def chat(
        self,
        messages: list[Message],
        *,
        node: str,
        model_role: str = "generation",
        max_tokens: int | None = None,
    ) -> LLMResult:
        del model_role  # одна модель на клиента
        started = time.monotonic()
        result = await self._chat_raw(messages, max_tokens=max_tokens)
        self._trace(node, result, started)
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
        """Judge не стримит: отдаём ответ одним куском (Protocol-совместимость)."""
        result = await self.chat(messages, node=node, model_role=model_role, max_tokens=max_tokens)
        if on_usage is not None:
            on_usage(result.prompt_tokens, result.completion_tokens)
        yield result.text

    async def structured(
        self,
        messages: list[Message],
        schema: type[T],
        *,
        node: str,
        model_role: str = "grading",
    ) -> tuple[T, LLMResult]:
        """JSON-режим + инструкция схемы; 1 retry на невалидный ответ."""
        del model_role
        schema_hint = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        prepared = [
            *messages,
            {
                "role": "user",
                "content": f"Ответь СТРОГО валидным JSON по схеме, без пояснений: {schema_hint}",
            },
        ]
        started = time.monotonic()
        result = await self._chat_raw(prepared, json_mode=True)
        self._trace(node, result, started)
        try:
            return schema.model_validate_json(result.text), result
        except ValidationError as first_error:
            retry_messages = [
                *prepared,
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
            retry = await self._chat_raw(retry_messages, json_mode=True)
            self._trace(f"{node}_retry", retry, started_retry)
            combined = LLMResult(
                text=retry.text,
                prompt_tokens=result.prompt_tokens + retry.prompt_tokens,
                completion_tokens=result.completion_tokens + retry.completion_tokens,
            )
            try:
                return schema.model_validate_json(retry.text), combined
            except ValidationError as exc:
                raise LLMFormatError(f"Невалидный structured-ответ узла {node}") from exc
