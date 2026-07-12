"""DocumentIR — единое промежуточное представление документа (ADR-002).

Все парсеры выдают его; chunker и content_hash потребляют только его.
Каноническая сериализация детерминирована — одинаковый вход даёт одинаковый
hash (инвариант идемпотентности).
"""

import hashlib
import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class BlockType(StrEnum):
    PARAGRAPH = "paragraph"
    TABLE = "table"
    CODE = "code"
    LIST = "list"


class Block(BaseModel):
    type: BlockType
    text: str
    # code: язык; table: подпись; служебные пометки парсеров
    meta: dict[str, Any] = Field(default_factory=dict)


class Section(BaseModel):
    """Секция под одним заголовком; вложенность — через children."""

    heading: str | None = None
    level: int = 0  # 0 — корень/без заголовка, 1..4 — H1..H4
    blocks: list[Block] = Field(default_factory=list)
    children: list["Section"] = Field(default_factory=list)


class DocumentIR(BaseModel):
    title: str
    source_type: str  # confluence | upload; уточнение формата — в meta
    root: Section
    meta: dict[str, Any] = Field(default_factory=dict)  # lang, mime, low_structure, url, ...

    def content_hash(self) -> str:
        """SHA-256 канонической сериализации нормализованного содержимого."""
        canonical = json.dumps(self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def iter_sections(self) -> list[tuple[list[str], Section]]:
        """Плоский обход: (путь заголовков от корня, секция)."""
        result: list[tuple[list[str], Section]] = []

        def walk(section: Section, path: list[str]) -> None:
            current = [*path, section.heading] if section.heading else path
            result.append((current, section))
            for child in section.children:
                walk(child, current)

        walk(self.root, [])
        return result
