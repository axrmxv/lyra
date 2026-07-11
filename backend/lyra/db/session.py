"""Async-движок и фабрика сессий SQLAlchemy."""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from lyra.core.config import Settings, get_settings


def build_engine(settings: Settings) -> AsyncEngine:
    dsn = settings.database_dsn.replace("postgresql://", "postgresql+asyncpg://")
    return create_async_engine(dsn, pool_pre_ping=True)


@lru_cache
def get_engine() -> AsyncEngine:
    return build_engine(get_settings())


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI-dependency: сессия на запрос, commit при успехе."""
    async with get_sessionmaker()() as session:
        yield session
