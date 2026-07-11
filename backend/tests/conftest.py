"""Фикстуры интеграционных тестов.

Требуется поднятый postgres (compose). БД lyra_test пересоздаётся на сессию:
alembic upgrade head, затем каждый тест — во вложенной транзакции с откатом.
Настройки подключения: env LYRA_DB_* (в контейнере — из .env; на хосте задать
LYRA_DB_HOST=localhost и пароль).
"""

import os
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from lyra.core.config import Settings, get_settings
from lyra.core.constants import DEFAULT_TENANT_ID

TEST_DB_NAME = "lyra_test"


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    settings = Settings(_env_file=None)
    return settings.model_copy(update={"db_name": TEST_DB_NAME})


@pytest.fixture(scope="session")
def migrated_db(test_settings: Settings) -> Iterator[Settings]:
    """alembic upgrade head на lyra_test (создать БД заранее: CREATE DATABASE lyra_test)."""
    env_backup = os.environ.get("LYRA_DB_NAME")
    os.environ["LYRA_DB_NAME"] = TEST_DB_NAME
    # lru-кэши могли зафиксировать настройки до подмены LYRA_DB_NAME
    # (например, тесты /health/ready вызывают get_settings раньше)
    get_settings.cache_clear()
    try:
        config = AlembicConfig("alembic.ini")
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        yield test_settings
    finally:
        if env_backup is None:
            os.environ.pop("LYRA_DB_NAME", None)
        else:
            os.environ["LYRA_DB_NAME"] = env_backup
        get_settings.cache_clear()


@pytest.fixture()
async def db_session(migrated_db: Settings) -> AsyncIterator[AsyncSession]:
    """Сессия во внешней транзакции с откатом — тесты не видят друг друга."""
    dsn = migrated_db.database_dsn.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(dsn)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        maker = async_sessionmaker(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        async with maker() as session:
            yield session
        await transaction.rollback()
    await engine.dispose()


@pytest.fixture()
def tenant_id() -> uuid.UUID:
    return DEFAULT_TENANT_ID
