"""honest_fallback: честный отказ вместо генерации без опоры (ADR-006/007, FR-9).

Полноценная ветка графа, не исключение: отказ + ближайшие найденные документы.
"""

from lyra.rag.deps import GraphDeps
from lyra.rag.state import DocumentRef, RagState

REFUSAL_TEXT = (
    "В базе знаний нет информации по этому вопросу. "
    "Возможно, будут полезны документы из списка ниже — либо уточните формулировку."
)
NEAREST_LIMIT = 3


async def honest_fallback(state: RagState, deps: GraphDeps) -> RagState:
    del deps
    state.draft_answer = REFUSAL_TEXT
    state.citations = []
    return state


def nearest_documents(state: RagState) -> list[DocumentRef]:
    seen: dict[str, DocumentRef] = {}
    for chunk in state.retrieved_chunks:
        key = str(chunk.document_id)
        if key not in seen:
            seen[key] = DocumentRef(
                document_id=chunk.document_id,
                title=str(chunk.meta.get("doc_title", "")),
                url=chunk.meta.get("url"),
            )
        if len(seen) >= NEAREST_LIMIT:
            break
    return list(seen.values())
