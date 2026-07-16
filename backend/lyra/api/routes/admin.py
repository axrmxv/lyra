"""Админ-эндпоинты: пользователи и коллекции (docs/api-contract.md §6).

RBAC: только admin (матрица docs/security-and-access.md §2).
"""

import uuid

from fastapi import APIRouter, Depends

from lyra.api.deps import SessionDep, require_role
from lyra.api.schemas.admin import (
    CollectionCreate,
    CollectionOut,
    CollectionPatch,
    CollectionsPage,
    EvalBaselineOut,
    EvalFailedItem,
    EvalRunAccepted,
    EvalRunOut,
    EvalRunRequest,
    UserCreate,
    UserPatch,
    UsersPage,
)
from lyra.api.schemas.auth import UserOut
from lyra.api.schemas.ingest import ReindexRequest
from lyra.core.auth import hash_password
from lyra.core.constants import DEFAULT_TENANT_ID
from lyra.core.errors import ConflictError, NotFoundError
from lyra.db.models import UserRole
from lyra.db.repositories import CollectionRepository, EvalRepository, UserRepository
from lyra.workers.tasks.evals import run_evals_task
from lyra.workers.tasks.ingest import reindex_collection

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)


@router.get("/users")
async def list_users(session: SessionDep, limit: int = 50, offset: int = 0) -> UsersPage:
    users, total = await UserRepository(session).list(DEFAULT_TENANT_ID, limit=limit, offset=offset)
    return UsersPage(items=[UserOut.model_validate(u) for u in users], total=total)


@router.post("/users", status_code=201)
async def create_user(body: UserCreate, session: SessionDep) -> UserOut:
    repo = UserRepository(session)
    if await repo.get_by_email(DEFAULT_TENANT_ID, body.email) is not None:
        raise ConflictError("Пользователь с таким email уже существует")
    user = await repo.create(
        DEFAULT_TENANT_ID,
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
    )
    await session.commit()
    return UserOut.model_validate(user)


@router.patch("/users/{user_id}")
async def patch_user(user_id: uuid.UUID, body: UserPatch, session: SessionDep) -> UserOut:
    user = await UserRepository(session).update(
        DEFAULT_TENANT_ID,
        user_id,
        role=body.role,
        is_active=body.is_active,
        password_hash=hash_password(body.password) if body.password else None,
    )
    if user is None:
        raise NotFoundError("Пользователь не найден")
    await session.commit()
    return UserOut.model_validate(user)


@router.post("/reindex", status_code=202)
async def reindex(body: ReindexRequest, session: SessionDep) -> dict[str, str]:
    """Переиндексация коллекции: новые версии всех документов (api-contract §6)."""
    collection = await CollectionRepository(session).get(DEFAULT_TENANT_ID, body.collection_id)
    if collection is None:
        raise NotFoundError("Коллекция не найдена")
    reindex_collection.delay(str(body.collection_id))
    return {"status": "queued", "collection_id": str(body.collection_id)}


@router.post("/eval-runs", status_code=202)
async def create_eval_run(body: EvalRunRequest, session: SessionDep) -> EvalRunAccepted:
    """Запуск eval-прогона в очереди evals (api-contract §6, UC-8)."""
    evals = EvalRepository(session)
    if body.dataset_id is not None:
        dataset = await evals.get_dataset(DEFAULT_TENANT_ID, body.dataset_id)
        if dataset is None:
            raise NotFoundError("Датасет не найден")
    else:
        dataset = await evals.get_or_create_dataset(DEFAULT_TENANT_ID, body.dataset_name)
    run = await evals.create_run(DEFAULT_TENANT_ID, dataset_id=dataset.id)
    await session.commit()
    run_evals_task.delay(str(run.id), dataset.name, body.judge)
    return EvalRunAccepted(run_id=run.id)


@router.get("/eval-runs/{run_id}")
async def get_eval_run(run_id: uuid.UUID, session: SessionDep) -> EvalRunOut:
    evals = EvalRepository(session)
    run = await evals.get_run(DEFAULT_TENANT_ID, run_id)
    if run is None:
        raise NotFoundError("Eval-run не найден")

    aggregate = dict(run.aggregate or {})
    baseline_delta = aggregate.pop("baseline_delta", None)
    failed_items: list[EvalFailedItem] = []
    if run.status.value == "completed":
        # Провальные items: низкий faithfulness или ложный отказ на answerable
        problem_records = []
        for record in await evals.list_records(DEFAULT_TENANT_ID, run_id):
            metrics = record.metrics or {}
            if metrics.get("kind") == "unanswerable":
                continue
            faithfulness = metrics.get("faithfulness")
            false_refusal = bool(metrics.get("refusal"))
            if (faithfulness is not None and faithfulness < 0.7) or false_refusal:
                problem_records.append((faithfulness if faithfulness is not None else 0.0, record))
        problem_records.sort(key=lambda entry: entry[0])
        for _score, record in problem_records[:10]:
            metrics = record.metrics or {}
            item = await evals.get_item(DEFAULT_TENANT_ID, record.item_id)
            failed_items.append(
                EvalFailedItem(
                    item_id=record.item_id,
                    question=item.question if item else "",
                    faithfulness=metrics.get("faithfulness"),
                    citation_validity=metrics.get("citation_validity"),
                    answer_relevance=metrics.get("answer_relevance"),
                )
            )
    return EvalRunOut(
        run_id=run.id,
        status=run.status.value,
        git_ref=run.git_ref,
        metrics=aggregate,
        baseline=EvalBaselineOut(delta=baseline_delta) if baseline_delta else None,
        failed_items=failed_items,
    )


@router.get("/collections")
async def list_collections(
    session: SessionDep, limit: int = 50, offset: int = 0
) -> CollectionsPage:
    collections, total = await CollectionRepository(session).list(
        DEFAULT_TENANT_ID, limit=limit, offset=offset
    )
    return CollectionsPage(
        items=[CollectionOut.model_validate(c) for c in collections], total=total
    )


@router.post("/collections", status_code=201)
async def create_collection(body: CollectionCreate, session: SessionDep) -> CollectionOut:
    collection = await CollectionRepository(session).create(
        DEFAULT_TENANT_ID,
        name=body.name,
        embedding_model=body.embedding_model,
        description=body.description,
        chunking_config=body.chunking_config,
    )
    await session.commit()
    return CollectionOut.model_validate(collection)


@router.patch("/collections/{collection_id}")
async def patch_collection(
    collection_id: uuid.UUID, body: CollectionPatch, session: SessionDep
) -> CollectionOut:
    collection = await CollectionRepository(session).update(
        DEFAULT_TENANT_ID,
        collection_id,
        name=body.name,
        description=body.description,
        chunking_config=body.chunking_config,
    )
    if collection is None:
        raise NotFoundError("Коллекция не найдена")
    await session.commit()
    return CollectionOut.model_validate(collection)
