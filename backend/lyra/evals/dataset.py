"""Загрузка golden dataset из JSONL и синк в eval_datasets/eval_items.

Датасет append-only: существующие items (по вопросу) не перезаписываются,
новые добавляются (.claude/rules/evals.md). Разметка источников в JSONL —
имена файлов корпуса (external_id); в БД пишутся резолвленные UUID
документов, поэтому синк выполняется после сида корпуса.
"""

import json
import uuid
from pathlib import Path

import structlog
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from lyra.core.constants import DEFAULT_TENANT_ID
from lyra.db.models import EvalItem, EvalItemKind
from lyra.db.repositories import DocumentRepository, EvalRepository

logger = structlog.get_logger(__name__)


class DatasetItem(BaseModel):
    """Строка golden.jsonl (схема — eval_items из data-model + служебные поля)."""

    id: str
    kind: EvalItemKind
    subset: str
    question: str
    ground_truth_answer: str | None = None
    expected_docs: list[str] = Field(default_factory=list)
    paraphrase_group: str | None = None
    reviewed: bool = False


def load_jsonl(path: Path) -> list[DatasetItem]:
    items = [
        DatasetItem.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ids = [item.id for item in items]
    if len(ids) != len(set(ids)):
        raise ValueError("Дубликаты id в датасете")
    return items


async def sync_dataset(
    session: AsyncSession, *, dataset_name: str, items: list[DatasetItem]
) -> tuple[uuid.UUID, dict[str, EvalItem]]:
    """Синк JSONL → БД; возвращает (dataset_id, jsonl-id → EvalItem).

    Разметка expected_docs резолвится в document_id; ненайденный документ —
    ошибка (датасет и корпус версионируются вместе)."""
    tenant_id = DEFAULT_TENANT_ID
    evals = EvalRepository(session)
    documents = DocumentRepository(session)

    dataset = await evals.get_or_create_dataset(tenant_id, dataset_name)
    mapping: dict[str, EvalItem] = {}
    created = 0
    for item in items:
        doc_ids: list[str] = []
        for external_id in item.expected_docs:
            document = await documents.find_by_external_id(tenant_id, external_id)
            if document is None:
                raise ValueError(
                    f"Датасет ссылается на документ {external_id}, которого нет в БД — "
                    "выполните сид корпуса (python -m lyra.evals seed)"
                )
            doc_ids.append(str(document.id))

        existing = await evals.get_item_by_question(tenant_id, dataset.id, item.question)
        if existing is None:
            existing = await evals.create_item(
                tenant_id,
                dataset_id=dataset.id,
                question=item.question,
                kind=item.kind,
                ground_truth_answer=item.ground_truth_answer,
                expected_doc_ids=doc_ids,
                reviewed=item.reviewed,
            )
            created += 1
        mapping[item.id] = existing

    await session.commit()
    logger.info("dataset_synced", dataset=dataset_name, items=len(items), created=created)
    return dataset.id, mapping
