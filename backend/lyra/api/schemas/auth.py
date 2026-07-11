"""Схемы /auth (docs/api-contract.md §1)."""

import uuid

from pydantic import BaseModel, ConfigDict

from lyra.db.models import UserRole


class LoginRequest(BaseModel):
    # Не EmailStr: он отвергает special-use домены (.local), на которых живут
    # демо-пользователи (admin@lyra.local); формат проверяется при создании
    email: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: UserRole
    is_active: bool


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut
