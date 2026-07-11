"""База репозиториев.

Каждый метод каждого репозитория принимает tenant_id (правило CLAUDE.md,
инвариант 7): в MVP это константа DEFAULT_TENANT_ID, в production — из JWT.
Прямые запросы к моделям вне репозиториев запрещены (.claude/rules/python.md).
"""

from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
