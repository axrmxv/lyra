"""Сид демо-корпуса в чистый стенд через штатный ingest-пайплайн.

evals — оркестрирующий слой уровня workers: зовёт домены ingest/rag напрямую.
Сид идемпотентен (content_hash в ingest_ir): повторный запуск на том же
корпусе даёт skipped_duplicate, изменённые файлы получают новую версию.
Запуск — CLI-процесс (python -m lyra.evals seed), не API (инвариант 1).
"""

from pathlib import Path

import structlog

from lyra.core.auth import hash_password
from lyra.core.config import get_settings
from lyra.core.constants import DEFAULT_TENANT_ID
from lyra.db.models import IngestJobKind, SourceType, UserRole
from lyra.db.repositories import (
    CollectionRepository,
    DocumentRepository,
    IngestJobRepository,
    SourceRepository,
    UserRepository,
)
from lyra.db.session import get_sessionmaker
from lyra.ingest.parsers import parse_document
from lyra.ingest.service import ingest_ir

logger = structlog.get_logger(__name__)

DEMO_COLLECTION_NAME = "Астра-Линк (демо-корпус)"
DEMO_SOURCE_NAME = "Демо-корпус evals"
SHOWCASE_COLLECTION_NAME = "Астра-Линк (витрина)"
EMBEDDING_MODEL = "BAAI/bge-m3"  # ADR-003


def _extract_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


async def seed_corpus(
    corpus_dir: Path,
    *,
    collection_name: str = DEMO_COLLECTION_NAME,
    source_name: str = DEMO_SOURCE_NAME,
) -> dict[str, int]:
    """Загружает все .md корпуса; возвращает счётчики по статусам job."""
    files = sorted(corpus_dir.glob("*.md"))
    if not files:
        raise FileNotFoundError(f"В {corpus_dir} нет .md-файлов корпуса")

    tenant_id = DEFAULT_TENANT_ID
    counts: dict[str, int] = {}
    maker = get_sessionmaker()
    async with maker() as session:
        collections = CollectionRepository(session)
        collection = await collections.get_by_name(tenant_id, collection_name)
        if collection is None:
            collection = await collections.create(
                tenant_id, name=collection_name, embedding_model=EMBEDDING_MODEL
            )
            await session.commit()

        sources = SourceRepository(session)
        source = await sources.get_upload_source(tenant_id, collection.id)
        if source is None:
            source = await sources.create(
                tenant_id,
                collection_id=collection.id,
                type_=SourceType.UPLOAD,
                name=source_name,
            )
            await session.commit()

        documents = DocumentRepository(session)
        jobs = IngestJobRepository(session)
        for index, path in enumerate(files, start=1):
            content = path.read_bytes()
            title = _extract_title(content.decode("utf-8"), fallback=path.name)
            document = await documents.get_by_external_id(tenant_id, source.id, path.name)
            if document is None:
                document = await documents.create(
                    tenant_id, source_id=source.id, external_id=path.name, title=title
                )
            job = await jobs.create(tenant_id, kind=IngestJobKind.UPLOAD, source_id=source.id)
            await session.commit()

            ir = parse_document(content, fmt="markdown", title=title)
            status = await ingest_ir(
                session,
                tenant_id=tenant_id,
                job_id=job.id,
                document_id=document.id,
                ir=ir,
            )
            counts[status.value] = counts.get(status.value, 0) + 1
            print(f"  [{index}/{len(files)}] {path.name}: {status.value}", flush=True)
            logger.info("seed_document", file=path.name, status=status.value)

    return counts


async def seed_demo_users() -> list[str]:
    """Demo-пользователи editor/viewer (пароли из env; admin сидится миграцией).

    Пустой пароль в конфиге — пользователь пропускается с предупреждением.
    """
    settings = get_settings()
    plan = [
        ("editor@lyra.local", UserRole.EDITOR, settings.demo_editor_password),
        ("viewer@lyra.local", UserRole.VIEWER, settings.demo_viewer_password),
    ]
    created: list[str] = []
    maker = get_sessionmaker()
    async with maker() as session:
        repo = UserRepository(session)
        for email, role, password in plan:
            if not password:
                print(f"  {email}: пропущен (пароль не задан в .env)", flush=True)
                continue
            if await repo.get_by_email(DEFAULT_TENANT_ID, email) is not None:
                print(f"  {email}: уже существует", flush=True)
                continue
            await repo.create(
                DEFAULT_TENANT_ID,
                email=email,
                password_hash=hash_password(password),
                role=role,
            )
            created.append(email)
            print(f"  {email}: создан ({role.value})", flush=True)
        await session.commit()
    return created
