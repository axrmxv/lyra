"""unique upload-source per collection

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6

Неявный upload-source коллекции должен быть ровно один (api-contract §2).
Без индекса параллельные загрузки в новую коллекцию создавали дубли source;
с ним гонку ловит IntegrityError, а репозиторий забирает чужую строку.

Дубли, накопленные до миграции, схлопываются: документы переносятся на
старейший source коллекции, лишние source удаляются.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "uq_sources_upload_per_collection"


def upgrade() -> None:
    connection = op.get_bind()
    duplicates = connection.execute(
        sa.text(
            """
            SELECT id, keeper FROM (
                SELECT id,
                       first_value(id) OVER w AS keeper,
                       row_number() OVER w AS rn
                  FROM sources
                 WHERE type = 'upload'
                WINDOW w AS (
                    PARTITION BY tenant_id, collection_id ORDER BY created_at, id
                )
            ) ranked
             WHERE rn > 1
            """
        )
    ).all()
    for source_id, keeper_id in duplicates:
        # Один и тот же external_id по обе стороны нарушил бы unique
        # (source_id, external_id). Автоматически такое не разрешить —
        # останавливаемся с внятным сообщением вместо порчи данных
        collisions = (
            connection.execute(
                sa.text(
                    """
                SELECT d.external_id FROM documents d
                 WHERE d.source_id = :dup
                   AND EXISTS (
                       SELECT 1 FROM documents k
                        WHERE k.source_id = :keeper AND k.external_id = d.external_id
                   )
                """
                ),
                {"keeper": keeper_id, "dup": source_id},
            )
            .scalars()
            .all()
        )
        if collisions:
            raise RuntimeError(
                f"Источники {keeper_id} и {source_id} содержат документы с одинаковым "
                f"external_id ({', '.join(collisions)}); объедините их вручную "
                "и повторите миграцию"
            )
        connection.execute(
            sa.text("UPDATE documents SET source_id = :keeper WHERE source_id = :dup"),
            {"keeper": keeper_id, "dup": source_id},
        )
        connection.execute(
            sa.text("UPDATE ingest_jobs SET source_id = :keeper WHERE source_id = :dup"),
            {"keeper": keeper_id, "dup": source_id},
        )
        connection.execute(sa.text("DELETE FROM sources WHERE id = :dup"), {"dup": source_id})

    op.create_index(
        INDEX_NAME,
        "sources",
        ["tenant_id", "collection_id"],
        unique=True,
        postgresql_where=sa.text("type = 'upload'"),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="sources")
