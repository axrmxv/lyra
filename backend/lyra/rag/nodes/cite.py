"""cite: детерминированный маппинг маркеров [n] → chunks (ADR-007, без LLM).

Валидация: маркер вне диапазона источников → cite_error → регенерация
(условное ребро). Quote — предложение chunk с максимальным пересечением
слов с ответом.
"""

import re

from lyra.rag.deps import GraphDeps
from lyra.rag.state import CitationItem, RagState
from lyra.retrieval.interfaces import ScoredChunk

MARKER = re.compile(r"\[(\d+)\]")
REFUSAL_PHRASE = "нет информации"


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _best_quote(chunk: ScoredChunk, answer: str) -> str:
    """Предложение chunk, наиболее пересекающееся с ответом по словам."""
    answer_words = {w.lower().strip(".,;:") for w in answer.split() if len(w) > 3}
    body = chunk.text.split("\n\n", 1)[-1]  # без префикса заголовков
    best_sentence, best_overlap = "", -1
    for sentence in _sentences(body):
        words = {w.lower().strip(".,;:") for w in sentence.split() if len(w) > 3}
        overlap = len(words & answer_words)
        if overlap > best_overlap:
            best_sentence, best_overlap = sentence, overlap
    return best_sentence[:300] or body[:300]


async def cite(state: RagState, deps: GraphDeps) -> RagState:
    del deps  # детерминированный узел — LLM не нужен
    answer = state.draft_answer or ""
    state.cite_error = None
    state.citations = []

    markers = sorted({int(m) for m in MARKER.findall(answer)})
    context_size = len(state.context_chunks)

    invalid = [m for m in markers if m < 1 or m > context_size]
    if invalid:
        state.cite_error = f"маркеры вне диапазона источников: {invalid}"
        return state

    if not markers and REFUSAL_PHRASE not in answer.lower():
        # Фактологический ответ без единой цитаты — формат нарушен (ADR-007)
        state.cite_error = "фактологический ответ без маркеров источников"
        return state

    for marker in markers:
        chunk = state.context_chunks[marker - 1]
        state.citations.append(
            CitationItem(
                id=marker,
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                document_title=str(chunk.meta.get("doc_title", "")),
                url=chunk.meta.get("url"),
                quote=_best_quote(chunk, answer),
                relevance_score=chunk.final_score,
            )
        )
    return state
