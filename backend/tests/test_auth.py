"""Тесты аутентификации: пароли, токены, негативные сценарии логина."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt as pyjwt
import pytest

from lyra.core.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    role_satisfies,
    verify_password,
)
from lyra.db.models import UserRole

SECRET = "test-secret"


def test_password_hash_roundtrip() -> None:
    password_hash = hash_password("s3cret-пароль")
    assert password_hash != "s3cret-пароль"
    assert verify_password("s3cret-пароль", password_hash)
    assert not verify_password("wrong", password_hash)


def test_token_roundtrip() -> None:
    user_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    token, expires_in = create_access_token(
        user_id=user_id, tenant_id=tenant_id, role=UserRole.EDITOR, secret=SECRET
    )
    assert expires_in == 3600
    payload = decode_access_token(token, secret=SECRET)
    assert payload["sub"] == str(user_id)
    assert payload["role"] == "editor"


def test_expired_token_rejected() -> None:
    token, _ = create_access_token(
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        role=UserRole.VIEWER,
        secret=SECRET,
        now=datetime.now(UTC) - timedelta(hours=2),
    )
    with pytest.raises(pyjwt.ExpiredSignatureError):
        decode_access_token(token, secret=SECRET)


def test_wrong_secret_rejected() -> None:
    token, _ = create_access_token(
        user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role=UserRole.VIEWER, secret=SECRET
    )
    with pytest.raises(pyjwt.InvalidTokenError):
        decode_access_token(token, secret="other-secret")


def test_role_hierarchy() -> None:
    assert role_satisfies(UserRole.ADMIN, UserRole.VIEWER)
    assert role_satisfies(UserRole.EDITOR, UserRole.VIEWER)
    assert role_satisfies(UserRole.VIEWER, UserRole.VIEWER)
    assert not role_satisfies(UserRole.VIEWER, UserRole.EDITOR)
    assert not role_satisfies(UserRole.EDITOR, UserRole.ADMIN)
