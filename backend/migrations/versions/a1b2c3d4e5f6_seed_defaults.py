"""seed defaults: tenant, admin, default collection

Revision ID: a1b2c3d4e5f6
Revises: dd7e7538c690

Email/пароль админа читаются из env (LYRA_ADMIN_EMAIL / LYRA_ADMIN_PASSWORD)
в момент выполнения миграции; hash — argon2. chunking_config —
docs/context-management.md §1.
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from lyra.core.auth import hash_password
from lyra.core.config import Settings  # не get_settings: см. комментарий в env.py
from lyra.core.constants import DEFAULT_TENANT_ID

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "dd7e7538c690"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# docs/context-management.md §1 (значения в токенах токенайзера bge-m3)
DEFAULT_CHUNKING_CONFIG = {
    "defaults": {"target_tokens": 512, "max_tokens": 768, "overlap_tokens": 64},
    "per_source_type": {
        "confluence": {"split": "headings"},
        "markdown": {"split": "headings"},
        "pdf": {"split": "headings", "fallback": {"target_tokens": 384, "max_tokens": 512}},
        "docx": {"split": "headings"},
        "txt": {"split": "paragraphs", "target_tokens": 384, "max_tokens": 512},
    },
    "atomic_blocks": {"table": {"max_tokens": 768}, "code": {"max_tokens": 768}},
}


def upgrade() -> None:
    settings = Settings()
    bind = op.get_bind()

    bind.execute(
        sa.text(
            "INSERT INTO tenants (id, name, status, created_at, updated_at) "
            "VALUES (:id, 'default', 'active', now(), now())"
        ),
        {"id": DEFAULT_TENANT_ID},
    )
    bind.execute(
        sa.text(
            "INSERT INTO users "
            "(id, tenant_id, email, password_hash, role, is_active, created_at, updated_at) "
            "VALUES (gen_random_uuid(), :tenant_id, :email, :password_hash, 'admin', true, "
            "now(), now())"
        ),
        {
            "tenant_id": DEFAULT_TENANT_ID,
            "email": settings.admin_email,
            "password_hash": hash_password(settings.admin_password),
        },
    )
    bind.execute(
        sa.text(
            "INSERT INTO collections "
            "(id, tenant_id, name, description, embedding_model, chunking_config, "
            "created_at, updated_at) "
            "VALUES (gen_random_uuid(), :tenant_id, 'default', "
            "'Коллекция по умолчанию', 'BAAI/bge-m3', CAST(:chunking_config AS jsonb), "
            "now(), now())"
        ),
        {
            "tenant_id": DEFAULT_TENANT_ID,
            "chunking_config": json.dumps(DEFAULT_CHUNKING_CONFIG, ensure_ascii=False),
        },
    )


def downgrade() -> None:
    """Удаляет ТОЛЬКО созданное этой миграцией: точные WHERE, не tenant-wide.

    К моменту downgrade в БД могут существовать другие строки того же tenant
    (созданные приложением/тестами) — широкий DELETE ловил FK-violation.
    """
    settings = Settings()
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM collections WHERE tenant_id = :tid "
            "AND name = 'default' AND NOT EXISTS "
            "(SELECT 1 FROM sources WHERE sources.collection_id = collections.id)"
        ),
        {"tid": DEFAULT_TENANT_ID},
    )
    bind.execute(
        sa.text("DELETE FROM users WHERE tenant_id = :tid AND email = :email"),
        {"tid": DEFAULT_TENANT_ID, "email": settings.admin_email},
    )
    bind.execute(
        sa.text(
            "DELETE FROM tenants WHERE id = :tid AND NOT EXISTS "
            "(SELECT 1 FROM users WHERE users.tenant_id = tenants.id)"
        ),
        {"tid": DEFAULT_TENANT_ID},
    )
