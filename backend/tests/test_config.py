"""Тесты конфигурации: чтение из env с префиксом LYRA_."""

import pytest

from lyra.core.config import Settings


def test_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.env == "dev"
    assert settings.db_host == "postgres"
    assert settings.redis_url == "redis://redis:6379/0"


def test_reads_env_with_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LYRA_ENV", "test")
    monkeypatch.setenv("LYRA_DB_PORT", "5433")
    monkeypatch.setenv("LYRA_DB_PASSWORD", "s3cret")
    settings = Settings(_env_file=None)
    assert settings.env == "test"
    assert settings.db_port == 5433
    assert settings.database_dsn == "postgresql://lyra:s3cret@postgres:5433/lyra"


def test_ignores_unprefixed_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "prod")
    settings = Settings(_env_file=None)
    assert settings.env == "dev"
