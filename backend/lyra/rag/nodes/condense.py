"""condense_question: история диалога → самостоятельный вопрос (ADR-006)."""

from lyra.rag.deps import GraphDeps
from lyra.rag.prompts import load_prompt
from lyra.rag.state import RagState

HISTORY_LAST_N = 6  # последних сообщений в промпт конденсации


async def condense_question(state: RagState, deps: GraphDeps) -> RagState:
    if not state.chat_history:
        state.condensed_question = state.question
        return state

    prompt, _ = load_prompt("condense")
    history_text = "\n".join(
        f"{message['role']}: {message['content']}"
        for message in state.chat_history[-HISTORY_LAST_N:]
    )
    result = await deps.llm.chat(
        [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": f"История:\n{history_text}\n\nНовый вопрос: {state.question}",
            },
        ],
        node="condense_question",
        model_role="grading",
        max_tokens=200,
    )
    state.bump_usage(result.prompt_tokens, result.completion_tokens)
    state.condensed_question = result.text.strip() or state.question
    return state
