"""Feedback API (docs/api-contract.md §5, UC-7): вход eval-контура."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from lyra.api.deps import SessionDep, require_role
from lyra.api.schemas.feedback import (
    FeedbackCreateRequest,
    FeedbackCreateResponse,
    FeedbackListResponse,
    FeedbackOut,
)
from lyra.core.errors import ForbiddenError, NotFoundError
from lyra.db.models import FeedbackRating, User, UserRole
from lyra.db.repositories import ChatRepository, FeedbackRepository

router = APIRouter(tags=["feedback"])

ViewerDep = Annotated[User, Depends(require_role(UserRole.VIEWER))]
AdminDep = Annotated[User, Depends(require_role(UserRole.ADMIN))]


@router.post("/feedback", status_code=201)
async def create_feedback(
    body: FeedbackCreateRequest, user: ViewerDep, session: SessionDep
) -> FeedbackCreateResponse:
    found = await ChatRepository(session).get_message_with_owner(user.tenant_id, body.message_id)
    if found is None:
        raise NotFoundError("Сообщение не найдено")
    _message, owner_id = found
    if owner_id != user.id:
        raise ForbiddenError("Фидбек — только на сообщения своих сессий")
    feedback = await FeedbackRepository(session).create(
        user.tenant_id,
        message_id=body.message_id,
        user_id=user.id,
        rating=body.rating,
        comment=body.comment,
    )
    await session.commit()
    return FeedbackCreateResponse(id=feedback.id)


@router.get("/feedback")
async def list_feedback(
    session: SessionDep,
    user: AdminDep,
    rating: Annotated[FeedbackRating | None, Query()] = None,
    created_from: Annotated[datetime | None, Query(alias="from")] = None,
    created_to: Annotated[datetime | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> FeedbackListResponse:
    repo = FeedbackRepository(session)
    items = await repo.list(
        user.tenant_id,
        rating=rating,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
        offset=offset,
    )
    total = await repo.count(
        user.tenant_id, rating=rating, created_from=created_from, created_to=created_to
    )
    return FeedbackListResponse(
        items=[FeedbackOut.model_validate(item) for item in items], total=total
    )
