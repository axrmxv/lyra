"""Тесты конфигурации: чтение из env с префиксом LYRA_."""

import os

import pytest

from lyra.core.config import Settings


@pytest.fixture()
def clean_lyra_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Изолирует тест от LYRA_-переменных внешнего окружения."""
    for key in list(os.environ):
        if key.startswith("LYRA_"):
            monkeypatch.delenv(key)


def test_defaults(clean_lyra_env: None) -> None:
    settings = Settings(_env_file=None)
    assert settings.env == "dev"
    assert settings.db_host == "postgres"
    assert settings.redis_url == "redis://redis:6379/0"


def test_reads_env_with_prefix(clean_lyra_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LYRA_ENV", "test")
    monkeypatch.setenv("LYRA_DB_PORT", "5433")
    monkeypatch.setenv("LYRA_DB_PASSWORD", "s3cret")
    settings = Settings(_env_file=None)
    assert settings.env == "test"
    assert settings.db_port == 5433
    assert settings.database_dsn == "postgresql://lyra:s3cret@postgres:5433/lyra"


def test_ignores_unprefixed_env(clean_lyra_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "prod")
    settings = Settings(_env_file=None)
    assert settings.env == "dev"
