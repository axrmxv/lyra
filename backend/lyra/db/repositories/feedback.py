"""Репозиторий фидбека (UC-7, FR-16): вход eval-контура фазы 6."""

import uuid
from datetime import datetime

from sqlalchemy import ColumnElement, func, select

from lyra.db.models import Feedback, FeedbackRating
from lyra.db.repositories.base import BaseRepository


class FeedbackRepository(BaseRepository):
    async def create(
        self,
        tenant_id: uuid.UUID,
        *,
        message_id: uuid.UUID,
        user_id: uuid.UUID,
        rating: FeedbackRating,
        comment: str | None = None,
    ) -> Feedback:
        feedback = Feedback(
            tenant_id=tenant_id,
            message_id=message_id,
            user_id=user_id,
            rating=rating,
            comment=comment,
        )
        self.session.add(feedback)
        await self.session.flush()
        return feedback

    def _filtered(
        self,
        tenant_id: uuid.UUID,
        rating: FeedbackRating | None,
        created_from: datetime | None,
        created_to: datetime | None,
    ) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = [Feedback.tenant_id == tenant_id]
        if rating is not None:
            conditions.append(Feedback.rating == rating)
        if created_from is not None:
            conditions.append(Feedback.created_at >= created_from)
        if created_to is not None:
            conditions.append(Feedback.created_at <= created_to)
        return conditions

    async def list(
        self,
        tenant_id: uuid.UUID,
        *,
        rating: FeedbackRating | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Feedback]:
        result = await self.session.execute(
            select(Feedback)
            .where(*self._filtered(tenant_id, rating, created_from, created_to))
            .order_by(Feedback.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars())

    async def count(
        self,
        tenant_id: uuid.UUID,
        *,
        rating: FeedbackRating | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(Feedback)
            .where(*self._filtered(tenant_id, rating, created_from, created_to))
        )
        return int(result.scalar_one())
