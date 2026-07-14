"""Интеграционные тесты траекторий RAG-графа (FakeLLM/FakeRetriever, без БД).

Траектории из ADR-006: happy path, corrective → sufficient, refusal после
исчерпания corrective, cite-error → retry, self_check fail → retry → pass,
self_check fail ×2 → refusal. Плюс лимиты LLM-вызовов.
"""

import uuid
from typing import Any

from lyra.core.config import Settings
from lyra.rag.deps import GraphDeps
from lyra.rag.graph import run_graph
from lyra.rag.state import RagState, SelfCheckResult, Sufficiency
from tests.rag_fakes import FakeLLM, FakeRetriever, make_chunk

TENANT = uuid.uuid4()

# rerank 0.3: выше нижнего порога (0.02), ниже auto-accept (0.6) —
# траектории проходят через LLM-judge, а не через верхнюю эвристику
GOOD_CHUNKS = [make_chunk(f"Отпуск составляет 28 дней, пункт {i}.", rerank=0.3) for i in range(4)]
WEAK_CHUNKS = [make_chunk("нерелевантный текст")]


def deps_with(llm: FakeLLM, retriever: FakeRetriever, **overrides: Any) -> GraphDeps:
    settings = Settings(_env_file=None).model_copy(update=overrides)
    return GraphDeps(retriever=retriever, llm=llm, settings=settings)  # type: ignore[arg-type]


def state(question: str = "Сколько дней отпуска?", **kwargs: Any) -> RagState:
    return RagState(question=question, tenant_id=TENANT, **kwargs)


async def test_happy_path() -> None:
    llm = FakeLLM(
        chat_responses={"generate": ["Отпуск составляет 28 дней [1]."]},
        structured_responses={
            "grade_sufficiency": [Sufficiency(sufficient=True, score=0.9)],
            "self_check": [SelfCheckResult(passed=True)],
        },
    )
    result = await run_graph(state(), deps_with(llm, FakeRetriever([GOOD_CHUNKS])))
    final = result.final
    assert final is not None and not final.refusal
    assert "[1]" in final.answer and final.citations[0].id == 1
    assert final.confidence.label in ("high", "medium")
    # Happy path без истории: grade + generate + self_check = 3 вызова (≤4)
    assert final.usage.llm_calls <= 4
    assert llm.calls == ["grade_sufficiency", "generate", "self_check"]


async def test_corrective_then_sufficient() -> None:
    llm = FakeLLM(
        chat_responses={
            "corrective_retrieve": ["отпуск количество дней политика"],
            "generate": ["Отпуск 28 дней [1]."],
        },
        structured_responses={
            "grade_sufficiency": [
                Sufficiency(sufficient=False, score=0.2, missing_aspects=["число дней"]),
                Sufficiency(sufficient=True, score=0.85),
            ],
            "self_check": [SelfCheckResult(passed=True)],
        },
    )
    retriever = FakeRetriever([GOOD_CHUNKS, GOOD_CHUNKS])  # 1-й retrieve + corrective
    result = await run_graph(state(), deps_with(llm, retriever))
    assert result.final is not None and not result.final.refusal
    assert result.corrective_iterations == 1
    assert retriever.queries[-1] == "отпуск количество дней политика"  # rewrite применён


async def test_refusal_after_corrective_exhausted() -> None:
    llm = FakeLLM(
        chat_responses={"corrective_retrieve": ["вариант 2", "вариант 3"]},
        structured_responses={},  # grade не дойдёт до LLM: эвристика (1 chunk) режет сразу
    )
    retriever = FakeRetriever([WEAK_CHUNKS, WEAK_CHUNKS, WEAK_CHUNKS])
    result = await run_graph(state("Что-то вне корпуса?"), deps_with(llm, retriever))
    final = result.final
    assert final is not None and final.refusal
    assert final.citations == []
    assert final.confidence.label == "low"
    assert final.nearest_documents  # ближайшие документы приложены
    assert result.corrective_iterations == 2  # лимит соблюдён


async def test_cite_error_retries_then_ok() -> None:
    llm = FakeLLM(
        chat_responses={"generate": ["Ответ [7]."], "retry_generate": []},
        structured_responses={
            "grade_sufficiency": [Sufficiency(sufficient=True, score=0.9)],
            "self_check": [SelfCheckResult(passed=True)],
        },
    )
    # retry_generate вызывает generate-узел → node="generate" в FakeLLM
    llm.chat_responses["generate"].append("Ответ [1].")
    result = await run_graph(state(), deps_with(llm, FakeRetriever([GOOD_CHUNKS])))
    final = result.final
    assert final is not None and not final.refusal
    assert result.generate_retries == 1
    assert final.citations[0].id == 1


async def test_self_check_fail_retry_pass() -> None:
    llm = FakeLLM(
        chat_responses={"generate": ["Отпуск 30 дней [1].", "Отпуск 28 дней [1]."]},
        structured_responses={
            "grade_sufficiency": [Sufficiency(sufficient=True, score=0.9)],
            "self_check": [
                SelfCheckResult(passed=False, unsupported_claims=["30 дней"]),
                SelfCheckResult(passed=True),
            ],
        },
    )
    result = await run_graph(state(), deps_with(llm, FakeRetriever([GOOD_CHUNKS])))
    assert result.final is not None and not result.final.refusal
    assert result.generate_retries == 1
    assert "28" in result.final.answer


async def test_self_check_fail_twice_refusal() -> None:
    llm = FakeLLM(
        chat_responses={"generate": ["Плохой ответ [1].", "Снова плохой [1]."]},
        structured_responses={
            "grade_sufficiency": [Sufficiency(sufficient=True, score=0.9)],
            "self_check": [
                SelfCheckResult(passed=False, unsupported_claims=["x"]),
                SelfCheckResult(passed=False, unsupported_claims=["y"]),
            ],
        },
    )
    result = await run_graph(state(), deps_with(llm, FakeRetriever([GOOD_CHUNKS])))
    final = result.final
    assert final is not None and final.refusal
    assert result.generate_retries == 1  # лимит регенераций соблюдён


async def test_worst_case_llm_calls_within_limit() -> None:
    """Худшая траектория: corrective×2 → generate → self_check fail → retry → fail → refusal."""
    llm = FakeLLM(
        chat_responses={
            "condense_question": ["самостоятельный вопрос"],
            "corrective_retrieve": ["v2", "v3"],
            "generate": ["Ответ [1].", "Ответ снова [1]."],
        },
        structured_responses={
            "grade_sufficiency": [
                Sufficiency(sufficient=False, score=0.2),
                Sufficiency(sufficient=False, score=0.2),
                Sufficiency(sufficient=True, score=0.6),
            ],
            "self_check": [
                SelfCheckResult(passed=False, unsupported_claims=["x"]),
                SelfCheckResult(passed=False, unsupported_claims=["y"]),
            ],
        },
    )
    retriever = FakeRetriever([GOOD_CHUNKS, GOOD_CHUNKS, GOOD_CHUNKS])
    result = await run_graph(
        state(chat_history=[{"role": "user", "content": "прошлый"}]),
        deps_with(llm, retriever),
    )
    assert result.final is not None and result.final.refusal
    # 1 condense + 3 grade + 2 rewrite + 2 generate + 2 self_check = 10 (ADR-006)
    assert result.final.usage.llm_calls == 10


async def test_degraded_flag_propagates() -> None:
    llm = FakeLLM(
        chat_responses={"generate": ["Ответ [1]."]},
        structured_responses={
            "grade_sufficiency": [Sufficiency(sufficient=True, score=0.9)],
            "self_check": [SelfCheckResult(passed=True)],
        },
    )
    retriever = FakeRetriever([GOOD_CHUNKS], degraded=True)
    result = await run_graph(state(), deps_with(llm, retriever))
    assert result.final is not None and result.final.degraded
