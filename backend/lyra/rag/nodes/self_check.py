"""self_check: LLM-judge faithfulness ответа против процитированных chunks
(ADR-006/007, ≤1 регенерация — лимит контролирует ребро графа)."""

from lyra.rag.deps import GraphDeps
from lyra.rag.nodes.cite import REFUSAL_PHRASE
from lyra.rag.prompts import load_prompt
from lyra.rag.state import RagState, SelfCheckResult


async def self_check(state: RagState, deps: GraphDeps) -> RagState:
    answer = state.draft_answer or ""
    if REFUSAL_PHRASE in answer.lower() and not state.citations:
        # Модель сама отказалась — проверять нечего (self_check.md, правило 3)
        state.self_check = SelfCheckResult(passed=True)
        return state

    prompt, _ = load_prompt("self_check")
    cited_ids = {citation.id for citation in state.citations}
    sources_text = "\n\n".join(
        f"[{i}] {chunk.text}"
        for i, chunk in enumerate(state.context_chunks, start=1)
        if i in cited_ids
    )
    verdict, usage = await deps.llm.structured(
        [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": (
                    f"Ответ ассистента:\n{answer}\n\n<ИСТОЧНИКИ>\n{sources_text}\n</ИСТОЧНИКИ>"
                ),
            },
        ],
        SelfCheckResult,
        node="self_check",
    )
    state.bump_usage(usage.prompt_tokens, usage.completion_tokens)
    state.self_check = verdict
    return state
