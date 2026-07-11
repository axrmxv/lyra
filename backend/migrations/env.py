"""Alembic async env: DSN из Settings, metadata из lyra.db.models."""

import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from lyra.core.config import Settings
from lyra.db.models import Base

target_metadata = Base.metadata


def _dsn() -> str:
    # Settings() напрямую, НЕ get_settings(): lru-кэш в долгоживущем процессе
    # (pytest) может хранить настройки, снятые до установки LYRA_DB_NAME,
    # и миграция уйдёт не в ту БД
    return Settings().database_dsn.replace("postgresql://", "postgresql+asyncpg://")


def run_migrations_offline() -> None:
    context.configure(
        url=_dsn(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_sync_migrations(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_dsn())
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
