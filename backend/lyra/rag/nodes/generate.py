"""generate: ответ строго по контексту с маркерами [n] (ADR-006/007).

Сборка контекста — бюджет context-management §2, порядок усечения фиксирован:
chunks целиком по score → усечение истории → флаг context_truncated.
Токены chunks — из token_count (приближение bge-m3, §2 прим.); история/вопрос —
оценкой chars/3.
"""

import structlog

from lyra.rag.deps import GraphDeps
from lyra.rag.prompts import load_prompt
from lyra.rag.state import RagState
from lyra.retrieval.interfaces import ScoredChunk
from lyra.retrieval.postprocess import merge_neighbors

logger = structlog.get_logger(__name__)

MIN_CONTEXT_CHUNKS = 3


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 3)


def build_context(state: RagState, deps: GraphDeps) -> tuple[list[ScoredChunk], bool, bool]:
    """(контекст-chunks, история_включена, context_truncated)."""
    budget = deps.settings.ctx_budget_chunks
    merged = merge_neighbors(state.retrieved_chunks)
    selected: list[ScoredChunk] = []
    used = 0
    for chunk in merged:
        if used + chunk.token_count > budget and selected:
            continue  # chunk не режется при сборке (§2) — пробуем следующие поменьше
        if used + chunk.token_count <= budget:
            selected.append(chunk)
            used += chunk.token_count

    include_history = bool(state.chat_history)
    truncated = False
    if len(selected) < MIN_CONTEXT_CHUNKS and include_history:
        include_history = False  # шаг 2 усечения: жертвуем историей
    if len(selected) < MIN_CONTEXT_CHUNKS and len(merged) > len(selected):
        truncated = True  # аномально крупные блоки — берём сколько влезло
    return selected, include_history, truncated


async def generate(state: RagState, deps: GraphDeps) -> RagState:
    system_prompt, _ = load_prompt("system_generate")
    context, include_history, truncated = build_context(state, deps)
    state.context_chunks = context
    if truncated:
        logger.warning("context_truncated", chunks=len(context))

    sources_text = "\n\n".join(f"[{i}] {chunk.text}" for i, chunk in enumerate(context, start=1))
    question = state.condensed_question or state.question

    messages = [{"role": "system", "content": system_prompt}]
    if include_history:
        history_budget = deps.settings.ctx_budget_history
        used = 0
        tail: list[dict[str, str]] = []
        for message in reversed(state.chat_history):
            tokens = _estimate_tokens(message["content"])
            if used + tokens > history_budget:
                break
            tail.insert(0, {"role": message["role"], "content": message["content"]})
            used += tokens
        messages.extend(tail)
    messages.append(
        {
            "role": "user",
            "content": (f"<ИСТОЧНИКИ>\n{sources_text}\n</ИСТОЧНИКИ>\n\nВопрос: {question}"),
        }
    )

    # Токены уходят в SSE по мере генерации (sink; NullSink вне chat-API)
    pieces: list[str] = []
    async for piece in deps.llm.chat_stream(
        messages,
        node="generate",
        max_tokens=deps.settings.ctx_budget_completion,
        on_usage=state.bump_usage,
    ):
        pieces.append(piece)
        await deps.sink.emit_token(piece)
    state.draft_answer = "".join(pieces).strip()
    return state
