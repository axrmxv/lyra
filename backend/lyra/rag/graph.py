"""Сборка LangGraph — топология строго по ADR-006 (инвариант 3 CLAUDE.md).

Циклы жёстко ограничены условными рёбрами: ≤2 corrective_retrieve,
≤1 регенерация (общий счётчик generate_retries на пути cite-error и
self_check-fail). Худший случай — 10 LLM-вызовов, happy path — 4.
"""

import time
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, Protocol

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from lyra.core.metrics import (
    ANSWERS_TOTAL,
    CORRECTIVE_TOTAL,
    DEGRADED_ANSWERS_TOTAL,
    GRAPH_NODE_SECONDS,
    SELF_CHECK_RETRY_TOTAL,
)
from lyra.rag.confidence import compute_confidence
from lyra.rag.deps import GraphDeps
from lyra.rag.nodes.cite import REFUSAL_PHRASE, cite
from lyra.rag.nodes.condense import condense_question
from lyra.rag.nodes.corrective import corrective_retrieve
from lyra.rag.nodes.fallback import honest_fallback, nearest_documents
from lyra.rag.nodes.generate import generate
from lyra.rag.nodes.grade import grade_sufficiency
from lyra.rag.nodes.retrieve import retrieve
from lyra.rag.nodes.self_check import self_check
from lyra.rag.state import AnswerPayload, RagState

MAX_CORRECTIVE = 2  # ADR-006
MAX_GENERATE_RETRIES = 1  # ADR-006

NodeFn = Callable[["RagState", "GraphDeps"], Awaitable["RagState"]]


class BoundNode(Protocol):
    """Сигнатура узла для langgraph._Node: параметр обязан называться state."""

    def __call__(self, state: RagState) -> Coroutine[Any, Any, RagState]: ...


# Стадия SSE-события status при входе в узел (api-contract §4). condense
# предшествует retrieve всегда — стадия retrieving закреплена за ним,
# чтобы UI получал прогресс с первого LLM-вызова; retrieve не эмитит.
STAGE_BY_NODE: dict[str, str | None] = {
    "condense_question": "retrieving",
    "retrieve": None,
    "grade_sufficiency": "grading",
    "corrective_retrieve": "corrective_retrieve",
    "generate": "generating",
    "retry_generate": "generating",
    "cite": None,
    "self_check": "self_check",
    "honest_fallback": None,
    "finalize": None,
}


async def finalize(state: RagState, deps: GraphDeps) -> RagState:
    del deps
    answer = state.draft_answer or ""
    refusal = not state.citations and (
        REFUSAL_PHRASE in answer.lower() or not answer or state.cite_error is not None
    )
    state.final = AnswerPayload(
        answer=answer,
        refusal=refusal,
        citations=state.citations,
        confidence=compute_confidence(state, refusal=refusal),
        degraded=state.degraded,
        nearest_documents=nearest_documents(state) if refusal else [],
        usage=state.usage,
    )
    return state


def _after_grade(state: RagState) -> str:
    assert state.sufficiency is not None
    if state.sufficiency.sufficient:
        return "generate"
    if state.corrective_iterations < MAX_CORRECTIVE:
        return "corrective_retrieve"
    return "honest_fallback"


def _after_cite(state: RagState) -> str:
    if state.cite_error is None:
        return "self_check"
    if state.generate_retries < MAX_GENERATE_RETRIES:
        return "retry_generate"
    return "honest_fallback"


def _after_self_check(state: RagState) -> str:
    assert state.self_check is not None
    if state.self_check.passed:
        return "finalize"
    if state.generate_retries < MAX_GENERATE_RETRIES:
        return "retry_generate"
    return "honest_fallback"


async def _retry_generate(state: RagState, deps: GraphDeps) -> RagState:
    state.generate_retries += 1
    return await generate(state, deps)


def _bind(name: str, fn: NodeFn, deps: GraphDeps) -> BoundNode:
    """Узел + SSE-статус при входе + latency-метрика (обвязка, не узлы —
    .claude/rules/rag-core.md)."""
    stage = STAGE_BY_NODE[name]

    async def node(state: RagState) -> RagState:
        if stage is not None:
            await deps.sink.emit_status(stage)
        started = time.monotonic()
        try:
            return await fn(state, deps)
        finally:
            GRAPH_NODE_SECONDS.labels(node=name).observe(time.monotonic() - started)

    return node


def build_graph(deps: GraphDeps) -> CompiledStateGraph[RagState, Any, Any, Any]:
    graph = StateGraph(RagState)
    graph.add_node("condense_question", _bind("condense_question", condense_question, deps))
    graph.add_node("retrieve", _bind("retrieve", retrieve, deps))
    graph.add_node("grade_sufficiency", _bind("grade_sufficiency", grade_sufficiency, deps))
    graph.add_node("corrective_retrieve", _bind("corrective_retrieve", corrective_retrieve, deps))
    graph.add_node("generate", _bind("generate", generate, deps))
    graph.add_node("retry_generate", _bind("retry_generate", _retry_generate, deps))
    graph.add_node("cite", _bind("cite", cite, deps))
    graph.add_node("self_check", _bind("self_check", self_check, deps))
    graph.add_node("honest_fallback", _bind("honest_fallback", honest_fallback, deps))
    graph.add_node("finalize", _bind("finalize", finalize, deps))

    graph.set_entry_point("condense_question")
    graph.add_edge("condense_question", "retrieve")
    graph.add_edge("retrieve", "grade_sufficiency")
    graph.add_conditional_edges("grade_sufficiency", _after_grade)
    graph.add_edge("corrective_retrieve", "grade_sufficiency")
    graph.add_edge("generate", "cite")
    graph.add_edge("retry_generate", "cite")
    graph.add_conditional_edges("cite", _after_cite)
    graph.add_conditional_edges("self_check", _after_self_check)
    graph.add_edge("honest_fallback", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


async def run_graph(state: RagState, deps: GraphDeps) -> RagState:
    """Прогон графа c учётом took_ms; вход/выход — RagState."""
    started = time.monotonic()
    app = build_graph(deps)
    raw = await app.ainvoke(state)
    result = RagState.model_validate(raw) if not isinstance(raw, RagState) else raw
    assert result.final is not None
    result.final.usage.took_ms = int((time.monotonic() - started) * 1000)
    # Счётчики исходов (FR-20) — в обвязке, узлы метрик не знают
    ANSWERS_TOTAL.labels(outcome="refusal" if result.final.refusal else "answered").inc()
    if result.corrective_iterations:
        CORRECTIVE_TOTAL.inc(result.corrective_iterations)
    if result.generate_retries:
        SELF_CHECK_RETRY_TOTAL.inc(result.generate_retries)
    if result.final.degraded:
        DEGRADED_ANSWERS_TOTAL.inc()
    return result
