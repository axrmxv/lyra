"""Критерий приёмки фазы 1: чистый цикл upgrade → downgrade → upgrade и seed."""

import asyncio
import os

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from lyra.core.config import Settings

pytestmark = pytest.mark.integration


def test_migration_cycle(migrated_db: Settings) -> None:
    """downgrade base → upgrade head поверх уже накатанной head-схемы."""
    os.environ["LYRA_DB_NAME"] = migrated_db.db_name
    config = AlembicConfig("alembic.ini")
    command.downgrade(config, "base")
    command.upgrade(config, "head")


def test_seed_present(migrated_db: Settings) -> None:
    async def check() -> tuple[int, str, str]:
        dsn = migrated_db.database_dsn.replace("postgresql://", "postgresql+asyncpg://")
        engine = create_async_engine(dsn)
        async with engine.connect() as conn:
            tenants = await conn.scalar(text("SELECT count(*) FROM tenants"))
            role = await conn.scalar(text("SELECT role FROM users LIMIT 1"))
            model = await conn.scalar(text("SELECT embedding_model FROM collections LIMIT 1"))
        await engine.dispose()
        return tenants or 0, str(role), str(model)

    tenants, role, model = asyncio.run(check())
    assert tenants == 1
    assert role == "admin"
    assert model == "BAAI/bge-m3"
