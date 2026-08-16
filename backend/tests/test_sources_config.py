"""config источника: форма по типу, отказ на секрет, срез для viewer.

Юнит-тесты — без БД и приложения: проверяется валидация и маппинг в ответ.
"""

import uuid

import pytest

from lyra.api.routes.sources import _source_out
from lyra.api.schemas.ingest import public_config, validate_source_config
from lyra.core.constants import DEFAULT_TENANT_ID
from lyra.core.errors import InvalidSourceConfigError, SecretInConfigError
from lyra.db.models import Source, SourceStatus, SourceType, User, UserRole

VALID_CONFLUENCE = {
    "base_url": "https://kb.example.com/wiki",
    "spaces": ["HR", "IT"],
    "email": "bot@example.com",
    "token_secret_ref": "CONFLUENCE_TOKEN",
}


def test_valid_confluence_config_passes() -> None:
    validate_source_config(SourceType.CONFLUENCE, VALID_CONFLUENCE)
    # upload-источник конфигурации не имеет
    validate_source_config(SourceType.UPLOAD, {})


def test_raw_token_in_config_rejected() -> None:
    """Регрессия: токен в config уезжал в БД открытым текстом."""
    config = {**VALID_CONFLUENCE, "token": "ghp_" + "a" * 36}
    with pytest.raises(SecretInConfigError) as excinfo:
        validate_source_config(SourceType.CONFLUENCE, config)
    assert excinfo.value.details["kinds"] == ["github_token"]
    # Сам секрет в ошибку не попадает — только тип находки
    assert "ghp_" not in excinfo.value.message


def test_unknown_key_rejected() -> None:
    with pytest.raises(InvalidSourceConfigError):
        validate_source_config(SourceType.CONFLUENCE, {**VALID_CONFLUENCE, "password_ref": "X"})


def test_missing_required_key_rejected() -> None:
    with pytest.raises(InvalidSourceConfigError) as excinfo:
        validate_source_config(SourceType.CONFLUENCE, {"base_url": "https://kb", "spaces": []})
    assert "spaces" in excinfo.value.message


def test_public_config_hides_internal_keys() -> None:
    assert public_config(VALID_CONFLUENCE) == {
        "base_url": VALID_CONFLUENCE["base_url"],
        "spaces": VALID_CONFLUENCE["spaces"],
    }


def _user(role: UserRole) -> User:
    return User(
        id=uuid.uuid4(),
        tenant_id=DEFAULT_TENANT_ID,
        email=f"{role.value}@lyra.local",
        password_hash="x",
        role=role,
        is_active=True,
    )


@pytest.mark.parametrize("role", [UserRole.VIEWER, UserRole.EDITOR])
def test_viewer_and_editor_do_not_see_internal_config(role: UserRole) -> None:
    source = Source(
        id=uuid.uuid4(),
        tenant_id=DEFAULT_TENANT_ID,
        collection_id=uuid.uuid4(),
        type=SourceType.CONFLUENCE,
        name="KB",
        config=VALID_CONFLUENCE,
        sync_schedule=None,
        sync_cursor=None,
        status=SourceStatus.ACTIVE,  # default проставляется при flush, здесь явно
    )
    assert "token_secret_ref" not in _source_out(source, _user(role)).config
    assert _source_out(source, _user(UserRole.ADMIN)).config == VALID_CONFLUENCE
