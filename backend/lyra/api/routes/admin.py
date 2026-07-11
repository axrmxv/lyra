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
    UserCreate,
    UserPatch,
    UsersPage,
)
from lyra.api.schemas.auth import UserOut
from lyra.core.auth import hash_password
from lyra.core.constants import DEFAULT_TENANT_ID
from lyra.core.errors import ConflictError, NotFoundError
from lyra.db.models import UserRole
from lyra.db.repositories import CollectionRepository, UserRepository

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
