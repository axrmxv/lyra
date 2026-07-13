"""Фасад RAG-ядра: answer_question — вход для chat-API (фаза 5) и evals (фаза 6)."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lyra.core.clients.llm import LLMClient, OllamaClient
from lyra.core.config import Settings
from lyra.rag.deps import GraphDeps
from lyra.rag.graph import run_graph
from lyra.rag.state import AnswerPayload, RagState
from lyra.retrieval.retriever import HybridRetriever


def build_deps(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    llm: LLMClient | None = None,
    retriever: HybridRetriever | None = None,
) -> GraphDeps:
    return GraphDeps(
        retriever=retriever or HybridRetriever(session_factory, settings),
        llm=llm
        or OllamaClient(
            settings.ollama_url,
            generation_model=settings.generation_model,
            grading_model=settings.grading_model,
            timeout_s=settings.llm_timeout_s,
            num_ctx=settings.llm_num_ctx,
        ),
        settings=settings,
    )


async def answer_question(
    question: str,
    *,
    tenant_id: uuid.UUID,
    deps: GraphDeps,
    chat_history: list[dict[str, str]] | None = None,
    collection_id: uuid.UUID | None = None,
) -> tuple[AnswerPayload, RagState]:
    """(итоговый ответ, финальный state — для graph_meta/аудита)."""
    state = RagState(
        question=question,
        chat_history=chat_history or [],
        collection_id=collection_id,
        tenant_id=tenant_id,
    )
    final_state = await run_graph(state, deps)
    assert final_state.final is not None
    return final_state.final, final_state
