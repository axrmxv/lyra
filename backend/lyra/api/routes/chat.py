"""Chat API: сессии, история, SSE-стрим ответа (docs/api-contract.md §4).

Порядок SSE-событий: status* → token* → final | error. Сообщения и цитаты
персистятся (messages, message_citations); graph_meta — вердикты и итерации
для отладки. Доступ — только к своим сессиям (403 на чужую, 404 на несуществующую).
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from lyra.api.deps import SessionDep, chat_rate_limit, require_role
from lyra.api.schemas.chat import (
    ChatMessageRequest,
    CitationOut,
    FinalEvent,
    MessageListResponse,
    MessageOut,
    SessionCreateResponse,
    SessionListResponse,
    SessionOut,
)
from lyra.core.clients.llm import LLMUnavailable
from lyra.core.concurrency import get_generation_gate
from lyra.core.config import get_settings
from lyra.core.errors import ForbiddenError, NotFoundError, OverloadedError
from lyra.db.models import ChatSession, MessageRole, User, UserRole
from lyra.db.repositories import ChatRepository
from lyra.db.session import get_sessionmaker
from lyra.rag.deps import GraphDeps
from lyra.rag.events import EventSink
from lyra.rag.service import answer_question, build_deps
from lyra.rag.state import AnswerPayload, RagState

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

ViewerDep = Annotated[User, Depends(require_role(UserRole.VIEWER))]

SESSION_TITLE_MAX = 60

DepsFactory = Callable[[EventSink], GraphDeps]


def get_deps_factory() -> DepsFactory:
    """Фабрика GraphDeps с per-request sink; в тестах подменяется override'ом."""
    settings = get_settings()
    maker = get_sessionmaker()

    def factory(sink: EventSink) -> GraphDeps:
        return build_deps(settings, maker, sink=sink)

    return factory


class _QueueSink:
    """EventSink → asyncio.Queue: граф пишет события, SSE-генератор читает."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()

    async def emit_status(self, stage: str) -> None:
        await self.queue.put(("status", {"stage": stage}))

    async def emit_token(self, text: str) -> None:
        await self.queue.put(("token", {"text": text}))


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _own_session(
    repo: ChatRepository, tenant_id: uuid.UUID, session_id: uuid.UUID, user: User
) -> ChatSession:
    chat_session = await repo.get_session(tenant_id, session_id)
    if chat_session is None:
        raise NotFoundError("Сессия не найдена")
    if chat_session.user_id != user.id:
        raise ForbiddenError("Доступ только к своим сессиям")
    return chat_session


@router.post("/sessions", status_code=201)
async def create_session(user: ViewerDep, session: SessionDep) -> SessionCreateResponse:
    chat_session = await ChatRepository(session).create_session(user.tenant_id, user_id=user.id)
    await session.commit()
    return SessionCreateResponse(session_id=chat_session.id)


@router.get("/sessions")
async def list_sessions(
    user: ViewerDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SessionListResponse:
    repo = ChatRepository(session)
    items = await repo.list_sessions(user.tenant_id, user.id, limit=limit, offset=offset)
    total = await repo.count_sessions(user.tenant_id, user.id)
    return SessionListResponse(
        items=[SessionOut.model_validate(item) for item in items], total=total
    )


@router.get("/sessions/{session_id}/messages")
async def list_messages(
    session_id: uuid.UUID,
    user: ViewerDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MessageListResponse:
    repo = ChatRepository(session)
    await _own_session(repo, user.tenant_id, session_id, user)
    messages = await repo.list_messages(user.tenant_id, session_id, limit=limit, offset=offset)
    total = await repo.count_messages(user.tenant_id, session_id)
    citations = await repo.list_citations_for_messages(
        user.tenant_id, [message.id for message in messages]
    )
    return MessageListResponse(
        items=[
            MessageOut(
                id=message.id,
                role=message.role.value,
                content=message.content,
                confidence=message.confidence,
                refusal=bool((message.graph_meta or {}).get("refusal")),
                created_at=message.created_at,
                citations=[CitationOut(**c) for c in citations.get(message.id, [])],
            )
            for message in messages
        ],
        total=total,
    )


@router.post("/sessions/{session_id}/messages", dependencies=[Depends(chat_rate_limit)])
async def post_message(
    session_id: uuid.UUID,
    body: ChatMessageRequest,
    user: ViewerDep,
    session: SessionDep,
    deps_factory: Annotated[DepsFactory, Depends(get_deps_factory)],
) -> StreamingResponse:
    settings = get_settings()
    repo = ChatRepository(session)
    await _own_session(repo, user.tenant_id, session_id, user)

    # История — до записи нового сообщения; хвост режется по конфигу,
    # точный токен-бюджет применяет сам граф (context-management §2)
    previous = await repo.list_messages(user.tenant_id, session_id)
    history = [
        {"role": message.role.value, "content": message.content}
        for message in previous[-settings.chat_history_messages :]
    ]

    await repo.add_message(
        user.tenant_id, session_id=session_id, role=MessageRole.USER, content=body.content
    )
    await repo.set_session_title(user.tenant_id, session_id, body.content[:SESSION_TITLE_MAX])
    await session.commit()

    gate = get_generation_gate()
    if not await gate.try_acquire():
        raise OverloadedError(
            "Генерация перегружена, попробуйте позже",
            retry_after_s=settings.llm_overload_retry_after_s,
        )

    # Контекст запроса не живёт дольше хендлера — trace_id фиксируем сейчас
    trace_id = str(structlog.contextvars.get_contextvars().get("trace_id", ""))
    tenant_id, user_id = user.tenant_id, user.id

    async def event_stream() -> AsyncIterator[str]:
        sink = _QueueSink()
        deps = deps_factory(sink)
        task = asyncio.create_task(
            answer_question(
                body.content,
                tenant_id=tenant_id,
                deps=deps,
                chat_history=history,
                collection_id=body.collection_id,
            )
        )
        task.add_done_callback(lambda _t: sink.queue.put_nowait(None))
        try:
            while True:
                item = await sink.queue.get()
                if item is None:
                    break
                kind, data = item
                yield _sse(kind, data)
            payload, final_state = task.result()
        except LLMUnavailable as exc:
            logger.warning("chat_llm_unavailable", error=str(exc))
            yield _sse("error", {"code": "llm_unavailable", "message": "LLM недоступна"})
            return
        except Exception:
            logger.exception("chat_stream_failed")
            yield _sse("error", {"code": "internal_error", "message": "Внутренняя ошибка"})
            return
        finally:
            if not task.done():
                task.cancel()
            gate.release()

        try:
            message_id = await _persist_answer(
                tenant_id,
                session_id=session_id,
                payload=payload,
                final_state=final_state,
                trace_id=trace_id,
            )
        except Exception:
            logger.exception("chat_persist_failed", user_id=str(user_id))
            yield _sse("error", {"code": "internal_error", "message": "Внутренняя ошибка"})
            return
        final = FinalEvent.from_payload(payload, message_id=message_id, trace_id=trace_id)
        yield _sse("final", final.model_dump(mode="json"))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _persist_answer(
    tenant_id: uuid.UUID,
    *,
    session_id: uuid.UUID,
    payload: AnswerPayload,
    final_state: RagState,
    trace_id: str,
) -> uuid.UUID:
    """Собственная сессия БД: request-сессия уже закрыта к моменту финала стрима."""
    async with get_sessionmaker()() as db:
        repo = ChatRepository(db)
        message = await repo.add_message(
            tenant_id,
            session_id=session_id,
            role=MessageRole.ASSISTANT,
            content=payload.answer,
            confidence=payload.confidence.model_dump(),
            trace_id=trace_id,
            # refusal дублируется в meta: история сообщений должна отличать
            # отказ от обычного ответа без повторного вычисления
            graph_meta={**final_state.meta_snapshot(), "refusal": payload.refusal},
        )
        await repo.add_citations(
            tenant_id,
            message_id=message.id,
            citations=[
                {
                    "chunk_id": item.chunk_id,
                    "marker": item.id,
                    "quote": item.quote,
                    "relevance_score": item.relevance_score,
                }
                for item in payload.citations
            ],
        )
        await db.commit()
        return message.id
