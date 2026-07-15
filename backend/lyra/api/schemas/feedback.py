"""Схемы /feedback (docs/api-contract.md §5, UC-7)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from lyra.db.models import FeedbackRating


class FeedbackCreateRequest(BaseModel):
    message_id: uuid.UUID
    rating: FeedbackRating
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackCreateResponse(BaseModel):
    id: uuid.UUID


class FeedbackOut(BaseModel):
    id: uuid.UUID
    message_id: uuid.UUID
    user_id: uuid.UUID
    rating: FeedbackRating
    comment: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class FeedbackListResponse(BaseModel):
    items: list[FeedbackOut]
    total: int
