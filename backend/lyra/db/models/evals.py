"""Eval-контур: датасеты, items, прогоны, записи (docs/data-model.md §2).

Датасет append-only (docs/eval-plan.md §4): items не редактируются задним
числом — исправление = is_active=False у старого + новый item.
"""

import uuid
from typing import Any

from sqlalchemy import Enum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from lyra.db.base import Base, IdTimestampMixin, TenantMixin
from lyra.db.models.enums import EvalItemKind, EvalRunStatus


class EvalDataset(IdTimestampMixin, TenantMixin, Base):
    __tablename__ = "eval_datasets"

    name: Mapped[str] = mapped_column(Text, unique=True)
    description: Mapped[str | None] = mapped_column(Text)


class EvalItem(IdTimestampMixin, TenantMixin, Base):
    __tablename__ = "eval_items"

    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("eval_datasets.id"))
    question: Mapped[str] = mapped_column(Text)
    ground_truth_answer: Mapped[str | None] = mapped_column(Text)
    expected_chunk_ids: Mapped[list[str] | None] = mapped_column(JSONB)
    expected_doc_ids: Mapped[list[str] | None] = mapped_column(JSONB)
    kind: Mapped[EvalItemKind] = mapped_column(
        Enum(EvalItemKind, name="eval_item_kind", values_callable=lambda e: [m.value for m in e])
    )
    # Синтетика без ручного ревью в golden set не попадает (eval-plan §2)
    reviewed: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)


class EvalRun(IdTimestampMixin, TenantMixin, Base):
    __tablename__ = "eval_runs"

    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("eval_datasets.id"))
    git_ref: Mapped[str | None] = mapped_column(Text)
    # Версии промптов, модели, retrieval-параметры — воспроизводимость run'а
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[EvalRunStatus] = mapped_column(
        Enum(EvalRunStatus, name="eval_run_status", values_callable=lambda e: [m.value for m in e]),
        default=EvalRunStatus.QUEUED,
    )
    aggregate: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class EvalRecord(IdTimestampMixin, TenantMixin, Base):
    __tablename__ = "eval_records"

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("eval_runs.id"))
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("eval_items.id"))
    answer: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    judge_raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
