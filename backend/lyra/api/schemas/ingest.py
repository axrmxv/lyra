"""Схемы ingest-эндпоинтов (docs/api-contract.md §2)."""

import json
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lyra.core.errors import InvalidSourceConfigError, SecretInConfigError
from lyra.db.models import (
    DocumentStatus,
    IngestJobKind,
    IngestJobStatus,
    SourceStatus,
    SourceType,
)
from lyra.ingest.secrets_scan import scan_text

# Ключи config, видные viewer'у: показывают, что синхронизируется. Остальное
# (email, token_secret_ref) — внутренний контур (security-and-access §5)
PUBLIC_CONFIG_KEYS = frozenset({"base_url", "spaces"})


class ConfluenceSourceConfig(BaseModel):
    """Конфигурация Confluence-источника (ingest/connectors/confluence.py).

    extra="forbid": лишние ключи — обычно попытка положить сюда сам токен.
    """

    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(min_length=1)
    spaces: list[str] = Field(min_length=1)
    email: str = ""
    # Только имя env-переменной; значение токена в БД не попадает
    token_secret_ref: str = "CONFLUENCE_TOKEN"


def validate_source_config(type_: SourceType, config: dict[str, Any]) -> None:
    """Проверка config до записи в БД: форма по типу источника плюс секреты.

    Секреты ищет тот же сканер, что защищает корпус при ingest, — отдельного
    набора паттернов для конфигурации не заводим. Ошибка доменная, а не
    ValueError в валидаторе: RequestValidationError вернул бы найденный
    секрет обратно в details.errors[].input.
    """
    findings = scan_text(json.dumps(config, ensure_ascii=False))
    if findings:
        kinds = sorted({finding.kind for finding in findings})
        raise SecretInConfigError(
            f"В config обнаружен секрет ({', '.join(kinds)}); токен передаётся "
            "только ссылкой token_secret_ref на env-переменную",
            details={"kinds": kinds},
        )
    if type_ is SourceType.CONFLUENCE:
        try:
            ConfluenceSourceConfig.model_validate(config)
        except ValidationError as exc:
            # Только имена полей и причины: значения могли бы нести секрет
            problems = [
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()
            ]
            raise InvalidSourceConfigError(
                f"Некорректный config confluence-источника ({'; '.join(problems)})"
            ) from exc


def public_config(config: dict[str, Any]) -> dict[str, Any]:
    """Срез config для ответа viewer'у."""
    return {key: value for key, value in config.items() if key in PUBLIC_CONFIG_KEYS}


class UploadAccepted(BaseModel):
    job_id: uuid.UUID
    document_id: uuid.UUID
    status: IngestJobStatus


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: IngestJobKind
    status: IngestJobStatus
    steps: dict[str, Any]
    error: str | None
    source_id: uuid.UUID | None
    document_version_id: uuid.UUID | None
    created_at: datetime


class JobsPage(BaseModel):
    items: list[JobOut]
    total: int


class SourceCreate(BaseModel):
    collection_id: uuid.UUID
    type: SourceType
    name: str = Field(min_length=1)
    # Секреты — только ссылкой token_secret_ref на env-переменную
    config: dict[str, Any] = Field(default_factory=dict)
    sync_schedule: str | None = None


class SourcePatch(BaseModel):
    name: str | None = None
    config: dict[str, Any] | None = None
    sync_schedule: str | None = None
    status: SourceStatus | None = None


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    collection_id: uuid.UUID
    type: SourceType
    name: str
    config: dict[str, Any]
    sync_schedule: str | None
    sync_cursor: dict[str, Any] | None
    status: SourceStatus


class SourcesPage(BaseModel):
    items: list[SourceOut]
    total: int


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_id: uuid.UUID
    external_id: str
    title: str
    url: str | None
    author: str | None
    status: DocumentStatus
    active_version_id: uuid.UUID | None
    created_at: datetime


class DocumentsPage(BaseModel):
    items: list[DocumentOut]
    total: int


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: int
    content_hash: str
    status: str
    created_at: datetime


class DocumentDetail(DocumentOut):
    versions: list[VersionOut]


class ReindexRequest(BaseModel):
    collection_id: uuid.UUID


class SyncAccepted(BaseModel):
    source_id: uuid.UUID
    status: str = "queued"
