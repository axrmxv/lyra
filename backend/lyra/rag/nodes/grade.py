"""grade_sufficiency: эвристики ДО LLM-judge (ADR-006) — экономия вызовов.

Эвристика insufficient: < min_candidates кандидатов ИЛИ лучший rerank-score
ниже порога. LLM-judge вызывается только когда эвристики прошли.
"""

from lyra.rag.deps import GraphDeps
from lyra.rag.prompts import load_prompt
from lyra.rag.state import RagState, Sufficiency

SNIPPET_CHARS = 500  # сниппет chunk в промпт grade (≈120 токенов, context-management §2)


async def grade_sufficiency(state: RagState, deps: GraphDeps) -> RagState:
    chunks = state.retrieved_chunks
    settings = deps.settings

    if len(chunks) < settings.sufficiency_min_candidates:
        state.sufficiency = Sufficiency(
            sufficient=False, score=0.0, missing_aspects=["найдено слишком мало фрагментов"]
        )
        return state

    scored = [c.rerank_score for c in chunks if c.rerank_score is not None]
    if scored and max(scored) < settings.sufficiency_min_rerank_score:
        state.sufficiency = Sufficiency(
            sufficient=False,
            score=max(scored),
            missing_aspects=["найденные фрагменты слабо релевантны вопросу"],
        )
        return state
    if scored and max(scored) >= settings.sufficiency_auto_accept_score:
        # Cross-encoder уверенно нашёл ответ — LLM-judge не нужен.
        # Асимметрия рисков: ложный insufficient = полный отказ пользователю,
        # ложный sufficient перехватывается генератором и self_check
        state.sufficiency = Sufficiency(sufficient=True, score=min(1.0, max(scored)))
        return state

    prompt, _ = load_prompt("grade")
    snippets = "\n\n".join(
        f"[{i}] {chunk.text[:SNIPPET_CHARS]}" for i, chunk in enumerate(chunks, start=1)
    )
    question = state.condensed_question or state.question
    verdict, usage = await deps.llm.structured(
        [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": (f"Вопрос: {question}\n\n<ФРАГМЕНТЫ>\n{snippets}\n</ФРАГМЕНТЫ>"),
            },
        ],
        Sufficiency,
        node="grade_sufficiency",
    )
    state.bump_usage(usage.prompt_tokens, usage.completion_tokens)
    state.sufficiency = verdict
    return state
