"""Аутентификация: argon2-хэши паролей и JWT HS256 (docs/security-and-access.md §1).

Токен живёт 1 час, refresh-токенов в MVP нет. Иерархия ролей —
viewer < editor < admin (§2): require_role сравнивает по рангу.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

from lyra.db.models import UserRole

TOKEN_TTL = timedelta(hours=1)
ALGORITHM = "HS256"

ROLE_RANK: dict[UserRole, int] = {
    UserRole.VIEWER: 0,
    UserRole.EDITOR: 1,
    UserRole.ADMIN: 2,
}

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerificationError:
        return False


def create_access_token(
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    role: UserRole,
    secret: str,
    now: datetime | None = None,
) -> tuple[str, int]:
    """Возвращает (token, expires_in_seconds)."""
    issued_at = now or datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "role": role.value,
        "iat": issued_at,
        "exp": issued_at + TOKEN_TTL,
    }
    token = jwt.encode(payload, secret, algorithm=ALGORITHM)
    return token, int(TOKEN_TTL.total_seconds())


def decode_access_token(token: str, *, secret: str) -> dict[str, Any]:
    """Поднимает jwt.InvalidTokenError (включая ExpiredSignatureError)."""
    payload: dict[str, Any] = jwt.decode(token, secret, algorithms=[ALGORITHM])
    return payload


def role_satisfies(actual: UserRole, minimum: UserRole) -> bool:
    return ROLE_RANK[actual] >= ROLE_RANK[minimum]
