"""Сборка LangGraph — топология строго по ADR-006 (инвариант 3 CLAUDE.md).

Циклы жёстко ограничены условными рёбрами: ≤2 corrective_retrieve,
≤1 регенерация (общий счётчик generate_retries на пути cite-error и
self_check-fail). Худший случай — 10 LLM-вызовов, happy path — 4.
"""

import time
from functools import partial
from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

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


def build_graph(deps: GraphDeps) -> CompiledStateGraph[RagState, Any, Any, Any]:
    graph = StateGraph(RagState)
    graph.add_node("condense_question", partial(condense_question, deps=deps))
    graph.add_node("retrieve", partial(retrieve, deps=deps))
    graph.add_node("grade_sufficiency", partial(grade_sufficiency, deps=deps))
    graph.add_node("corrective_retrieve", partial(corrective_retrieve, deps=deps))
    graph.add_node("generate", partial(generate, deps=deps))
    graph.add_node("retry_generate", partial(_retry_generate, deps=deps))
    graph.add_node("cite", partial(cite, deps=deps))
    graph.add_node("self_check", partial(self_check, deps=deps))
    graph.add_node("honest_fallback", partial(honest_fallback, deps=deps))
    graph.add_node("finalize", partial(finalize, deps=deps))

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
    return result
