"""retrieve: гибридный поиск через Retriever (фаза 3) — результат в state."""

from lyra.rag.deps import GraphDeps
from lyra.rag.state import RagState
from lyra.retrieval.interfaces import SearchFilters


async def retrieve(state: RagState, deps: GraphDeps) -> RagState:
    query = state.condensed_question or state.question
    result = await deps.retriever.retrieve(
        query,
        tenant_id=state.tenant_id,
        filters=SearchFilters(collection_id=state.collection_id),
        top_k=deps.settings.rag_top_k,
        rerank=True,
    )
    state.retrieved_chunks = result.chunks
    state.degraded = state.degraded or result.degraded
    return state
