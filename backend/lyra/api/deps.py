"""FastAPI-dependencies: сессия БД, текущий пользователь, require_role.

Каждый новый эндпоинт обязан использовать require_role и получить строку
в RBAC-матрице docs/security-and-access.md §2 + тест (.claude/rules/api.md).
"""

import uuid
from collections.abc import Callable
from typing import Annotated

import jwt as pyjwt
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from lyra.core.auth import decode_access_token, role_satisfies
from lyra.core.config import get_settings
from lyra.core.constants import DEFAULT_TENANT_ID
from lyra.core.errors import ForbiddenError, UnauthorizedError
from lyra.db.models import User, UserRole
from lyra.db.repositories import UserRepository
from lyra.db.session import get_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def current_user(request: Request, session: SessionDep) -> User:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise UnauthorizedError("Требуется заголовок Authorization: Bearer <token>")
    token = auth_header.removeprefix("Bearer ").strip()
    try:
        payload = decode_access_token(token, secret=get_settings().jwt_secret)
    except pyjwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Токен истёк") from exc
    except pyjwt.InvalidTokenError as exc:
        raise UnauthorizedError("Невалидный токен") from exc

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise UnauthorizedError("Невалидный токен") from exc
    user = await UserRepository(session).get(DEFAULT_TENANT_ID, user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("Пользователь не найден или деактивирован")
    return user


CurrentUserDep = Annotated[User, Depends(current_user)]


def require_role(minimum: UserRole) -> Callable[[User], User]:
    def dependency(user: CurrentUserDep) -> User:
        if not role_satisfies(user.role, minimum):
            raise ForbiddenError(f"Требуется роль не ниже {minimum.value}")
        return user

    return dependency
