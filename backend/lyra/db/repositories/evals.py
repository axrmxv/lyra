"""Репозиторий eval-контура: датасеты, items, runs, records."""

import uuid
from typing import Any

from sqlalchemy import select

from lyra.db.models import EvalDataset, EvalItem, EvalItemKind, EvalRecord, EvalRun, EvalRunStatus
from lyra.db.repositories.base import BaseRepository


class EvalRepository(BaseRepository):
    async def get_or_create_dataset(self, tenant_id: uuid.UUID, name: str) -> EvalDataset:
        result = await self.session.execute(select(EvalDataset).where(EvalDataset.name == name))
        dataset = result.scalar_one_or_none()
        if dataset is None:
            dataset = EvalDataset(tenant_id=tenant_id, name=name)
            self.session.add(dataset)
            await self.session.flush()
        return dataset

    async def get_dataset(self, tenant_id: uuid.UUID, dataset_id: uuid.UUID) -> EvalDataset | None:
        result = await self.session.execute(
            select(EvalDataset).where(
                EvalDataset.tenant_id == tenant_id, EvalDataset.id == dataset_id
            )
        )
        return result.scalar_one_or_none()

    async def get_item_by_question(
        self, tenant_id: uuid.UUID, dataset_id: uuid.UUID, question: str
    ) -> EvalItem | None:
        result = await self.session.execute(
            select(EvalItem).where(
                EvalItem.tenant_id == tenant_id,
                EvalItem.dataset_id == dataset_id,
                EvalItem.question == question,
            )
        )
        return result.scalar_one_or_none()

    async def create_item(
        self,
        tenant_id: uuid.UUID,
        *,
        dataset_id: uuid.UUID,
        question: str,
        kind: EvalItemKind,
        ground_truth_answer: str | None = None,
        expected_doc_ids: list[str] | None = None,
        expected_chunk_ids: list[str] | None = None,
        reviewed: bool = False,
    ) -> EvalItem:
        item = EvalItem(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            question=question,
            kind=kind,
            ground_truth_answer=ground_truth_answer,
            expected_doc_ids=expected_doc_ids,
            expected_chunk_ids=expected_chunk_ids,
            reviewed=reviewed,
        )
        self.session.add(item)
        await self.session.flush()
        return item

    async def list_active_items(
        self, tenant_id: uuid.UUID, dataset_id: uuid.UUID
    ) -> list[EvalItem]:
        result = await self.session.execute(
            select(EvalItem)
            .where(
                EvalItem.tenant_id == tenant_id,
                EvalItem.dataset_id == dataset_id,
                EvalItem.is_active.is_(True),
            )
            .order_by(EvalItem.created_at)
        )
        return list(result.scalars())

    async def get_item(self, tenant_id: uuid.UUID, item_id: uuid.UUID) -> EvalItem | None:
        result = await self.session.execute(
            select(EvalItem).where(EvalItem.tenant_id == tenant_id, EvalItem.id == item_id)
        )
        return result.scalar_one_or_none()

    async def create_run(
        self,
        tenant_id: uuid.UUID,
        *,
        dataset_id: uuid.UUID,
        git_ref: str | None = None,
        config_snapshot: dict[str, Any] | None = None,
    ) -> EvalRun:
        run = EvalRun(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            git_ref=git_ref,
            config_snapshot=config_snapshot or {},
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def get_run(self, tenant_id: uuid.UUID, run_id: uuid.UUID) -> EvalRun | None:
        result = await self.session.execute(
            select(EvalRun).where(EvalRun.tenant_id == tenant_id, EvalRun.id == run_id)
        )
        return result.scalar_one_or_none()

    async def update_run(
        self,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        *,
        status: EvalRunStatus | None = None,
        aggregate: dict[str, Any] | None = None,
        config_snapshot: dict[str, Any] | None = None,
        git_ref: str | None = None,
    ) -> EvalRun | None:
        run = await self.get_run(tenant_id, run_id)
        if run is None:
            return None
        if status is not None:
            run.status = status
        if aggregate is not None:
            run.aggregate = aggregate
        if config_snapshot is not None:
            run.config_snapshot = config_snapshot
        if git_ref is not None:
            run.git_ref = git_ref
        await self.session.flush()
        return run

    async def latest_completed_run(
        self, tenant_id: uuid.UUID, dataset_id: uuid.UUID
    ) -> EvalRun | None:
        result = await self.session.execute(
            select(EvalRun)
            .where(
                EvalRun.tenant_id == tenant_id,
                EvalRun.dataset_id == dataset_id,
                EvalRun.status == EvalRunStatus.COMPLETED,
            )
            .order_by(EvalRun.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def add_record(
        self,
        tenant_id: uuid.UUID,
        *,
        run_id: uuid.UUID,
        item_id: uuid.UUID,
        answer: str | None,
        citations: list[dict[str, Any]] | None,
        metrics: dict[str, Any] | None,
        judge_raw: dict[str, Any] | None = None,
    ) -> EvalRecord:
        record = EvalRecord(
            tenant_id=tenant_id,
            run_id=run_id,
            item_id=item_id,
            answer=answer,
            citations=citations,
            metrics=metrics,
            judge_raw=judge_raw,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def list_records(self, tenant_id: uuid.UUID, run_id: uuid.UUID) -> list[EvalRecord]:
        result = await self.session.execute(
            select(EvalRecord)
            .where(EvalRecord.tenant_id == tenant_id, EvalRecord.run_id == run_id)
            .order_by(EvalRecord.created_at)
        )
        return list(result.scalars())
