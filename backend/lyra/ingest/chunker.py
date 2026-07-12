"""Structure-aware chunking (ADR-002, параметры — docs/context-management.md §1).

Правила:
- границы — заголовки IR; внутри секции блоки копятся до target_tokens;
- overlap только при разрезе длинной секции (хвост предыдущего chunk);
- таблицы/код атомарны; таблица > max — split по строкам с повторением шапки;
- контекстный заголовок "{doc_title} > {headings_path}" — префикс текста;
- детерминированность: одинаковый IR + конфиг → одинаковые chunks.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from lyra.ingest.ir import BlockType, DocumentIR
from lyra.ingest.tokenizer import count_tokens

CYRILLIC = re.compile(r"[а-яё]", re.IGNORECASE)


@dataclass
class ChunkDraft:
    text: str
    token_count: int
    ordinal: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChunkingParams:
    target_tokens: int = 512
    max_tokens: int = 768
    overlap_tokens: int = 64

    @classmethod
    def from_config(cls, config: dict[str, Any], source_format: str) -> "ChunkingParams":
        defaults: dict[str, Any] = dict(config.get("defaults", {}))
        per_type: dict[str, Any] = dict(config.get("per_source_type", {}).get(source_format, {}))
        merged = {**defaults, **{k: v for k, v in per_type.items() if isinstance(v, int)}}
        known = {k: v for k, v in merged.items() if k in cls.__dataclass_fields__}
        return cls(**known)


def _detect_lang(text: str) -> str:
    letters = sum(ch.isalpha() for ch in text)
    if letters == 0:
        return "ru"
    return "ru" if len(CYRILLIC.findall(text)) / letters > 0.3 else "en"


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [part for part in parts if part.strip()]


def _tail_by_tokens(text: str, limit: int) -> str:
    """Хвост текста ~limit токенов по границам предложений (для overlap).

    Единственное предложение длиннее лимита (текст без пунктуации) режется
    по словам — иначе overlap рос бы неограниченно.
    """
    tail: list[str] = []
    total = 0
    for sentence in reversed(_sentences(text)):
        tokens = count_tokens(sentence)
        if total + tokens > limit and tail:
            break
        tail.insert(0, sentence)
        total += tokens
    result = " ".join(tail)
    if count_tokens(result) > limit:
        words = result.split()
        while len(words) > 1 and count_tokens(" ".join(words)) > limit:
            words = words[len(words) // 2 :]
        result = " ".join(words)
    return result


def _split_table(text: str, max_tokens: int) -> list[tuple[str, dict[str, Any]]]:
    """Таблица > max: split по строкам, шапка повторяется (context-management §5)."""
    lines = text.splitlines()
    if len(lines) < 3:
        return [(text, {})]
    header = lines[:2]
    header_tokens = count_tokens("\n".join(header))
    parts: list[list[str]] = []
    current: list[str] = []
    current_tokens = header_tokens
    for row in lines[2:]:
        row_tokens = count_tokens(row)
        if current and current_tokens + row_tokens > max_tokens:
            parts.append(current)
            current, current_tokens = [], header_tokens
        current.append(row)
        current_tokens += row_tokens
    if current:
        parts.append(current)
    total = len(parts)
    return [
        ("\n".join(header + rows), {"table_part": f"{idx}/{total}"} if total > 1 else {})
        for idx, rows in enumerate(parts, start=1)
    ]


def chunk_document(
    ir: DocumentIR,
    *,
    chunking_config: dict[str, Any],
    doc_meta: dict[str, Any],
) -> list[ChunkDraft]:
    """doc_meta: url, source_updated_at, source_type — попадают в metadata chunk."""
    source_format = str(ir.meta.get("format", "txt"))
    params = ChunkingParams.from_config(chunking_config, source_format)
    if ir.meta.get("low_structure"):
        fallback = chunking_config.get("per_source_type", {}).get("pdf", {}).get("fallback", {})
        params = ChunkingParams(
            target_tokens=fallback.get("target_tokens", 384),
            max_tokens=fallback.get("max_tokens", 512),
            overlap_tokens=params.overlap_tokens,
        )

    chunks: list[ChunkDraft] = []
    ordinal = 0

    def base_metadata(headings_path: list[str], block_type: str) -> dict[str, Any]:
        return {
            "source_type": ir.source_type,
            "doc_title": ir.title,
            "headings_path": headings_path,
            "block_type": block_type,
            "url": doc_meta.get("url"),
            "source_updated_at": doc_meta.get("source_updated_at"),
        }

    def prefix_for(headings_path: list[str]) -> str:
        return " > ".join([ir.title, *headings_path])

    def emit(text: str, headings_path: list[str], block_type: str, extra: dict[str, Any]) -> None:
        nonlocal ordinal
        full_text = f"{prefix_for(headings_path)}\n\n{text}"
        # lang — естественный язык (ru|en, схема metadata data-model);
        # язык кода передаётся отдельным ключом code_lang через extra
        metadata = {**base_metadata(headings_path, block_type), "lang": _detect_lang(text)} | extra
        chunks.append(
            ChunkDraft(
                text=full_text,
                token_count=count_tokens(full_text),
                ordinal=ordinal,
                metadata=metadata,
            )
        )
        ordinal += 1

    for headings_path, section in ir.iter_sections():
        pending: list[str] = []
        pending_tokens = 0

        def flush(headings: list[str]) -> None:
            nonlocal pending, pending_tokens
            if pending:
                emit("\n\n".join(pending), headings, "text", {})
                pending, pending_tokens = [], 0

        for block in section.blocks:
            if block.type == BlockType.TABLE:
                flush(headings_path)
                for part_text, extra in _split_table(block.text, params.max_tokens):
                    emit(part_text, headings_path, "table", extra)
                continue
            if block.type == BlockType.CODE:
                flush(headings_path)
                emit(block.text, headings_path, "code", {"code_lang": block.meta.get("lang", "")})
                continue

            block_tokens = count_tokens(block.text)
            if block_tokens > params.max_tokens:
                # Аномально длинный абзац: режем по предложениям c overlap
                flush(headings_path)
                current: list[str] = []
                current_tokens = 0
                for sentence in _sentences(block.text):
                    sentence_tokens = count_tokens(sentence)
                    if current and current_tokens + sentence_tokens > params.target_tokens:
                        text = " ".join(current)
                        emit(text, headings_path, "text", {})
                        overlap = _tail_by_tokens(text, params.overlap_tokens)
                        current = [overlap] if overlap else []
                        current_tokens = count_tokens(overlap) if overlap else 0
                    current.append(sentence)
                    current_tokens += sentence_tokens
                if current:
                    emit(" ".join(current), headings_path, "text", {})
                continue

            if pending and pending_tokens + block_tokens > params.target_tokens:
                previous_text = "\n\n".join(pending)
                flush(headings_path)
                overlap = _tail_by_tokens(previous_text, params.overlap_tokens)
                if overlap:
                    pending, pending_tokens = [overlap], count_tokens(overlap)
            pending.append(block.text)
            pending_tokens += block_tokens

        flush(headings_path)

    return chunks
