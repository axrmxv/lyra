"""Схемы /admin: пользователи и коллекции (docs/api-contract.md §6)."""

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from lyra.api.schemas.auth import UserOut
from lyra.db.models import UserRole


class UserCreate(BaseModel):
    # Лёгкая проверка формата вместо EmailStr — см. комментарий в schemas/auth.py
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8)
    role: UserRole = UserRole.VIEWER


class UserPatch(BaseModel):
    role: UserRole | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8)


class UsersPage(BaseModel):
    items: list[UserOut]
    total: int


class CollectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    embedding_model: str
    chunking_config: dict[str, Any]


class CollectionCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    # Дефолт — контракт индекса ADR-003
    embedding_model: str = "BAAI/bge-m3"
    chunking_config: dict[str, Any] = Field(default_factory=dict)


class CollectionPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    chunking_config: dict[str, Any] | None = None


class CollectionsPage(BaseModel):
    items: list[CollectionOut]
    total: int
