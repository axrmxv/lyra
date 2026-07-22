"""self_check: LLM-judge faithfulness ответа против процитированных chunks
(ADR-006/007, ≤1 регенерация — лимит контролирует ребро графа)."""

import re

from lyra.rag.deps import GraphDeps
from lyra.rag.nodes.cite import REFUSAL_PHRASE
from lyra.rag.prompts import load_prompt
from lyra.rag.state import RagState, SelfCheckResult

# Markdown-эмфазис ломает верификацию: модель принимает выделенный фрагмент
# за границу значимого текста и не подтверждает факт, стоящий рядом с ним.
# Замер на реальном чанке: факт внутри **...** подтверждается, тот же факт
# сразу после закрывающих ** — нет (3/3 прогона, оба варианта формулировки).
# Проверяющему разметка не нужна — снимаем её с обеих сторон сравнения.
_EMPHASIS_RE = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", re.DOTALL)


def strip_emphasis(text: str) -> str:
    """Снимает **жирный** / __жирный__, сохраняя текст и маркеры [n].

    Одиночные `*` и `_` не трогаем: они встречаются в коде и идентификаторах
    (snake_case), а на верификацию не влияют.
    """
    return _EMPHASIS_RE.sub(r"\2", text)


async def self_check(state: RagState, deps: GraphDeps) -> RagState:
    answer = state.draft_answer or ""
    if REFUSAL_PHRASE in answer.lower() and not state.citations:
        # Модель сама отказалась — проверять нечего (self_check.md, правило 3)
        state.self_check = SelfCheckResult(passed=True)
        return state

    prompt, _ = load_prompt("self_check")
    cited_ids = {citation.id for citation in state.citations}
    # Нормализуем только то, что уходит в проверку; state.draft_answer и текст
    # chunks остаются как есть — пользователь и цитаты не затрагиваются.
    answer = strip_emphasis(answer)
    sources_text = "\n\n".join(
        f"[{i}] {strip_emphasis(chunk.text)}"
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
