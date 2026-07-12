"""PDF → DocumentIR (pymupdf): эвристика заголовков по размеру шрифта,
вырезание колонтитулов, fallback low_structure (ADR-002).

Заголовок: короткий блок со шрифтом заметно крупнее медианы тела.
Колонтитул: одинаковый текст на большинстве страниц в крайних 8% высоты.
"""

import io
import statistics
from collections import Counter
from typing import Any

import pymupdf

from lyra.ingest.ir import Block, BlockType, DocumentIR, Section
from lyra.ingest.parsers.base import ParserError

HEADING_FONT_RATIO = 1.15
HEADING_MAX_CHARS = 120
EDGE_ZONE = 0.08  # доля высоты страницы сверху/снизу для детекта колонтитулов
REPEAT_THRESHOLD = 0.6  # текст встречается на >60% страниц → колонтитул


def _table_to_markdown(rows: list[list[str | None]]) -> str:
    cleaned = [[(cell or "").replace("\n", " ").strip() for cell in row] for row in rows]
    cleaned = [row for row in cleaned if any(row)]
    if not cleaned:
        return ""
    lines = ["| " + " | ".join(cleaned[0]) + " |", "|" + "---|" * len(cleaned[0])]
    lines += ["| " + " | ".join(row) + " |" for row in cleaned[1:]]
    return "\n".join(lines)


def _extract_page_tables(page: Any) -> tuple[list[str], list[Any]]:
    """(markdown-таблицы страницы, их bbox — для исключения строк из текста)."""
    markdowns: list[str] = []
    bboxes: list[Any] = []
    try:
        tables = page.find_tables()
    except Exception:  # редкие падения детектора таблиц не должны ронять парсинг
        return [], []
    for table in tables.tables:
        markdown = _table_to_markdown(table.extract())
        if markdown:
            markdowns.append(markdown)
            bboxes.append(pymupdf.Rect(table.bbox))  # type: ignore[no-untyped-call]  # тайпинги pymupdf
    return markdowns, bboxes


def _extract_lines(document: Any) -> tuple[list[dict[str, Any]], dict[int, list[str]]]:
    """Строки со шрифтом/позицией + таблицы по страницам.

    Строки внутри bbox таблиц исключаются из текстового потока — таблица
    попадает в IR атомарным TABLE-блоком (ADR-002).
    document: pymupdf.Document — Any, т.к. тайпинги pymupdf неполные.
    """
    lines: list[dict[str, Any]] = []
    page_tables: dict[int, list[str]] = {}
    for page_number in range(document.page_count):
        page = document[page_number]
        height = page.rect.height or 1.0
        markdowns, table_bboxes = _extract_page_tables(page)
        if markdowns:
            page_tables[page_number] = markdowns
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                text = "".join(span["text"] for span in line.get("spans", [])).strip()
                if not text:
                    continue
                line_rect = pymupdf.Rect(line["bbox"])  # type: ignore[no-untyped-call]  # тайпинги pymupdf
                if any(bbox.intersects(line_rect) for bbox in table_bboxes):
                    continue
                size = max((span["size"] for span in line["spans"]), default=0.0)
                lines.append(
                    {
                        "text": text,
                        "size": round(size, 1),
                        "y_rel": line["bbox"][1] / height,
                        "page": page_number,
                    }
                )
    return lines, page_tables


def _detect_repeated_edges(lines: list[dict[str, Any]], page_count: int) -> set[str]:
    edge_texts = Counter(
        line["text"] for line in lines if line["y_rel"] < EDGE_ZONE or line["y_rel"] > 1 - EDGE_ZONE
    )
    return {
        text
        for text, count in edge_texts.items()
        if page_count > 1 and count / page_count >= REPEAT_THRESHOLD
    }


def parse_pdf(content: bytes, *, title: str) -> DocumentIR:
    try:
        document: Any = pymupdf.open(  # type: ignore[no-untyped-call]  # тайпинги pymupdf неполные
            stream=io.BytesIO(content), filetype="pdf"
        )
    except Exception as exc:
        raise ParserError(f"Не удалось открыть PDF: {exc}") from exc

    with document:
        page_count = document.page_count
        lines, page_tables = _extract_lines(document)

    if not lines and not page_tables:
        raise ParserError("PDF не содержит извлекаемого текста (скан без OCR?)")

    repeated = _detect_repeated_edges(lines, page_count)
    lines = [
        line
        for line in lines
        if line["text"] not in repeated and not line["text"].strip().isdigit()
    ]

    if lines:
        body_median = statistics.median(line["size"] for line in lines)
        heading_sizes = sorted(
            {
                line["size"]
                for line in lines
                if line["size"] >= body_median * HEADING_FONT_RATIO
                and len(line["text"]) <= HEADING_MAX_CHARS
            },
            reverse=True,
        )[:4]
        size_to_level = {size: level for level, size in enumerate(heading_sizes, start=1)}
    else:  # документ только из таблиц
        size_to_level = {}

    root = Section()
    stack: list[Section] = [root]
    paragraph: list[str] = []
    current_page = 0

    def flush() -> None:
        nonlocal paragraph
        text = " ".join(paragraph).strip()
        if text:
            stack[-1].blocks.append(
                Block(type=BlockType.PARAGRAPH, text=text, meta={"page": current_page + 1})
            )
        paragraph = []

    def flush_page_tables(page_number: int) -> None:
        for markdown in page_tables.pop(page_number, []):
            stack[-1].blocks.append(
                Block(type=BlockType.TABLE, text=markdown, meta={"page": page_number + 1})
            )

    for index, line in enumerate(lines):
        current_page = line["page"]
        level = size_to_level.get(line["size"])
        if level is not None and len(line["text"]) <= HEADING_MAX_CHARS:
            flush()
            section = Section(heading=line["text"], level=level)
            while len(stack) > 1 and stack[-1].level >= level:
                stack.pop()
            stack[-1].children.append(section)
            stack.append(section)
        else:
            paragraph.append(line["text"])
            # Пустые строки в line-режиме недоступны — граница абзаца = граница страницы
            is_last = index == len(lines) - 1
            if is_last or lines[index + 1]["page"] != current_page:
                flush()
                flush_page_tables(current_page)
    flush()
    # Таблицы страниц без текстовых строк (или последней страницы)
    for page_number in sorted(page_tables):
        flush_page_tables(page_number)

    low_structure = not size_to_level
    return DocumentIR(
        title=title,
        source_type="upload",
        root=root,
        meta={"format": "pdf", "pages": page_count, "low_structure": low_structure},
    )
