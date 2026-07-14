"""corrective_retrieve: LLM-rewrite запроса → повторный retrieval (ADR-006, ≤2).

Лимит итераций контролирует условное ребро графа — узел только инкрементирует.
"""

from lyra.rag.deps import GraphDeps
from lyra.rag.nodes.retrieve import retrieve
from lyra.rag.prompts import load_prompt
from lyra.rag.state import RagState


async def corrective_retrieve(state: RagState, deps: GraphDeps) -> RagState:
    prompt, _ = load_prompt("rewrite")
    question = state.condensed_question or state.question
    missing = ""
    if state.sufficiency and state.sufficiency.missing_aspects:
        missing = "\nНедостающие аспекты: " + "; ".join(state.sufficiency.missing_aspects)
    result = await deps.llm.chat(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Исходный запрос: {question}{missing}"},
        ],
        node="corrective_retrieve",
        model_role="grading",
        max_tokens=100,
    )
    state.bump_usage(result.prompt_tokens, result.completion_tokens)
    rewritten = result.text.strip()
    if rewritten:
        state.condensed_question = rewritten
    state.corrective_iterations += 1
    return await retrieve(state, deps)
