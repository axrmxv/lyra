"""Юнит-тесты узлов RAG-графа с FakeLLM — каждый узел изолированно."""

import uuid
from typing import Any

from lyra.core.config import Settings
from lyra.rag.confidence import compute_confidence
from lyra.rag.deps import GraphDeps
from lyra.rag.nodes.cite import cite
from lyra.rag.nodes.condense import condense_question
from lyra.rag.nodes.fallback import honest_fallback, nearest_documents
from lyra.rag.nodes.generate import build_context, generate
from lyra.rag.nodes.grade import grade_sufficiency
from lyra.rag.nodes.self_check import self_check, strip_emphasis
from lyra.rag.state import CitationItem, RagState, SelfCheckResult, Sufficiency
from tests.rag_fakes import FakeLLM, FakeRetriever, make_chunk

TENANT = uuid.uuid4()


def make_deps(
    llm: FakeLLM | None = None, retriever: FakeRetriever | None = None, **overrides: Any
) -> GraphDeps:
    settings = Settings(_env_file=None).model_copy(update=overrides)
    return GraphDeps(
        retriever=retriever or FakeRetriever([]),  # type: ignore[arg-type]
        llm=llm or FakeLLM(),  # type: ignore[arg-type]
        settings=settings,
    )


def make_state(**kwargs: Any) -> RagState:
    kwargs.setdefault("question", "Сколько дней отпуска?")
    kwargs.setdefault("tenant_id", TENANT)
    return RagState(**kwargs)


# --- condense ---


async def test_condense_skips_without_history() -> None:
    llm = FakeLLM()
    state = await condense_question(make_state(), make_deps(llm))
    assert state.condensed_question == state.question
    assert llm.calls == []  # LLM не дёргался


async def test_condense_uses_history() -> None:
    llm = FakeLLM(chat_responses={"condense_question": ["Сколько дней отпуска во второй год?"]})
    state = make_state(
        question="А во второй год?",
        chat_history=[{"role": "user", "content": "Сколько дней отпуска в первый год?"}],
    )
    state = await condense_question(state, make_deps(llm))
    assert state.condensed_question == "Сколько дней отпуска во второй год?"
    assert state.usage.llm_calls == 1


# --- grade: эвристики до LLM ---


async def test_grade_insufficient_too_few_candidates_no_llm() -> None:
    llm = FakeLLM()
    state = make_state(retrieved_chunks=[make_chunk("один")])
    state = await grade_sufficiency(state, make_deps(llm))
    assert state.sufficiency is not None and not state.sufficiency.sufficient
    assert llm.calls == []  # эвристика сработала без LLM


async def test_grade_insufficient_low_scores_no_llm() -> None:
    llm = FakeLLM()
    chunks = [make_chunk(f"c{i}", rerank=0.001) for i in range(4)]
    state = make_state(retrieved_chunks=chunks)
    state = await grade_sufficiency(state, make_deps(llm))
    assert state.sufficiency is not None and not state.sufficiency.sufficient
    assert llm.calls == []


async def test_grade_auto_accept_on_confident_rerank_no_llm() -> None:
    """Верхняя эвристика: cross-encoder уверен → sufficient без LLM-judge."""
    llm = FakeLLM()
    chunks = [make_chunk(f"c{i}", rerank=0.85 if i == 0 else 0.1) for i in range(4)]
    state = make_state(retrieved_chunks=chunks)
    state = await grade_sufficiency(state, make_deps(llm))
    assert state.sufficiency is not None and state.sufficiency.sufficient
    assert llm.calls == []


async def test_grade_calls_llm_when_heuristics_pass() -> None:
    llm = FakeLLM(
        structured_responses={"grade_sufficiency": [Sufficiency(sufficient=True, score=0.9)]}
    )
    chunks = [make_chunk(f"c{i}", rerank=0.3) for i in range(4)]  # между порогами эвристик
    state = make_state(retrieved_chunks=chunks)
    state = await grade_sufficiency(state, make_deps(llm))
    assert state.sufficiency is not None and state.sufficiency.sufficient
    assert llm.calls == ["grade_sufficiency"]


# --- generate: бюджет контекста ---


async def test_generate_respects_chunk_budget() -> None:
    llm = FakeLLM(chat_responses={"generate": ["Ответ [1]."]})
    big = [make_chunk(f"большой {i}", tokens=600, rerank=0.9 - i * 0.1) for i in range(5)]
    deps = make_deps(llm, ctx_budget_chunks=1500)  # влезает только 2 по 600
    state = make_state(retrieved_chunks=big)
    state = await generate(state, deps)
    assert len(state.context_chunks) == 2
    assert state.draft_answer is not None and "[1]" in state.draft_answer
    assert state.usage.prompt_tokens == 100  # on_usage из стрима


async def test_generate_drops_history_for_min_chunks() -> None:
    chunks = [make_chunk(f"c{i}", tokens=700, rerank=0.9) for i in range(3)]
    deps = make_deps(ctx_budget_chunks=1500)
    state = make_state(
        retrieved_chunks=chunks,
        chat_history=[{"role": "user", "content": "прошлый вопрос"}],
    )
    context, include_history, _ = build_context(state, deps)
    assert len(context) == 2  # только 2 влезло
    assert include_history is False  # история пожертвована (шаг 2 усечения §2)


# --- cite ---


def _generated_state(answer: str, n_context: int = 2) -> RagState:
    state = make_state(
        draft_answer=answer,
        context_chunks=[
            make_chunk(f"Отпуск составляет 28 дней. Прочее {i}.", title=f"doc{i}")
            for i in range(n_context)
        ],
    )
    return state


async def test_cite_maps_markers() -> None:
    state = await cite(
        _generated_state("Отпуск 28 дней [1]. Заявление за неделю [2]."), make_deps()
    )
    assert state.cite_error is None
    assert [c.id for c in state.citations] == [1, 2]
    assert all(c.quote for c in state.citations)


async def test_cite_out_of_range_marker_is_error() -> None:
    state = await cite(_generated_state("Ответ [99]."), make_deps())
    assert state.cite_error is not None
    assert state.citations == []


async def test_cite_factual_answer_without_markers_is_error() -> None:
    state = await cite(_generated_state("Отпуск составляет 28 дней."), make_deps())
    assert state.cite_error is not None


async def test_cite_refusal_without_markers_ok() -> None:
    state = await cite(
        _generated_state("В базе знаний нет информации по этому вопросу."), make_deps()
    )
    assert state.cite_error is None
    assert state.citations == []


# --- self_check ---


async def test_self_check_pass() -> None:
    llm = FakeLLM(structured_responses={"self_check": [SelfCheckResult(passed=True)]})
    state = _generated_state("Отпуск 28 дней [1].")
    state.citations = [
        CitationItem(
            id=1,
            chunk_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            document_title="d",
            url=None,
            quote="q",
            relevance_score=0.5,
        )
    ]
    state = await self_check(state, make_deps(llm))
    assert state.self_check is not None and state.self_check.passed


def test_strip_emphasis_removes_bold_keeps_text() -> None:
    assert strip_emphasis("из офиса **не менее 2 дней** — во вторник") == (
        "из офиса не менее 2 дней — во вторник"
    )
    assert strip_emphasis("__жирный__ текст") == "жирный текст"
    # Маркеры цитат и многострочность не страдают
    assert strip_emphasis("**срок** 3 года [1]\nвторая строка") == "срок 3 года [1]\nвторая строка"


def test_strip_emphasis_keeps_single_markers() -> None:
    # snake_case и одиночные звёздочки — не эмфазис, трогать нельзя
    assert strip_emphasis("поле max_tokens и 2 * 2") == "поле max_tokens и 2 * 2"
    assert strip_emphasis("* пункт списка") == "* пункт списка"


async def test_self_check_strips_markdown_before_verification() -> None:
    """Разметка в чанке сбивала верификацию — в модель уходит чистый текст (#26)."""
    llm = FakeLLM(structured_responses={"self_check": [SelfCheckResult(passed=True)]})
    state = _generated_state("Якорные дни — **вторник и четверг**. [1]")
    state.context_chunks = [
        make_chunk("из офиса **не менее 2 дней в неделю** — во вторник и четверг")
    ]
    state.citations = [
        CitationItem(
            id=1,
            chunk_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            document_title="d",
            url=None,
            quote="q",
            relevance_score=0.5,
        )
    ]
    state = await self_check(state, make_deps(llm))

    sent = llm.messages["self_check"][0][-1]["content"]
    assert "**" not in sent
    assert "не менее 2 дней в неделю — во вторник и четверг" in sent
    assert "[1]" in sent  # маркеры цитат сохранены
    # Исходный черновик не тронут — пользователь получает форматирование
    assert "**вторник и четверг**" in (state.draft_answer or "")


async def test_self_check_skips_refusal() -> None:
    llm = FakeLLM()
    state = make_state(draft_answer="В базе знаний нет информации по этому вопросу.")
    state = await self_check(state, make_deps(llm))
    assert state.self_check is not None and state.self_check.passed
    assert llm.calls == []


# --- fallback и confidence ---


async def test_fallback_and_nearest_documents() -> None:
    state = make_state(
        retrieved_chunks=[make_chunk("a", title="Doc-A"), make_chunk("b", title="Doc-B")]
    )
    state = await honest_fallback(state, make_deps())
    assert state.draft_answer is not None and "нет информации" in state.draft_answer.lower()
    nearest = nearest_documents(state)
    assert [d.title for d in nearest] == ["Doc-A", "Doc-B"]


def test_confidence_aggregation() -> None:
    state = _generated_state("Ответ [1].")
    state.sufficiency = Sufficiency(sufficient=True, score=0.9)
    state.self_check = SelfCheckResult(passed=True)
    state.citations = [
        CitationItem(
            id=1,
            chunk_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            document_title="d",
            url=None,
            quote="q",
            relevance_score=0.5,
        )
    ]
    confidence = compute_confidence(state, refusal=False)
    assert confidence.label == "high"
    refused = compute_confidence(state, refusal=True)
    assert refused.label == "low" and refused.score == 0.0


def test_confidence_self_check_failure_lowers_score() -> None:
    """Провал self_check снижает score (в finalize он попадает только
    через refusal-ветку, но вес компонента проверяем напрямую)."""

    def confidence_for(passed: bool) -> float:
        state = _generated_state("Ответ [1].")
        state.sufficiency = Sufficiency(sufficient=True, score=0.9)
        state.self_check = SelfCheckResult(passed=passed)
        state.citations = [
            CitationItem(
                id=1,
                chunk_id=uuid.uuid4(),
                document_id=uuid.uuid4(),
                document_title="d",
                url=None,
                quote="q",
                relevance_score=0.5,
            )
        ]
        return compute_confidence(state, refusal=False).score

    assert confidence_for(True) - confidence_for(False) >= 0.15
