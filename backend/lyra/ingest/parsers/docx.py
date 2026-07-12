"""DOCX → DocumentIR: секции по стилям Heading 1..4, таблицы в markdown."""

import io

from docx import Document as DocxDocument
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph

from lyra.ingest.ir import Block, BlockType, DocumentIR, Section
from lyra.ingest.parsers.base import ParserError


def _heading_level(paragraph: DocxParagraph) -> int | None:
    style = (paragraph.style.name or "").lower() if paragraph.style else ""
    if style.startswith("heading "):
        try:
            level = int(style.removeprefix("heading ").strip())
        except ValueError:
            return None
        return level if 1 <= level <= 4 else 4
    return None


def _table_to_markdown(table: DocxTable) -> str:
    rows = [[cell.text.strip().replace("\n", " ") for cell in row.cells] for row in table.rows]
    if not rows:
        return ""
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * len(rows[0])]
    lines += ["| " + " | ".join(row) + " |" for row in rows[1:]]
    return "\n".join(lines)


def parse_docx(content: bytes, *, title: str) -> DocumentIR:
    try:
        document = DocxDocument(io.BytesIO(content))
    except Exception as exc:  # библиотека кидает разнотипные ошибки на битых файлах
        raise ParserError(f"Не удалось открыть DOCX: {exc}") from exc

    root = Section()
    stack: list[Section] = [root]

    # iter_inner_content сохраняет порядок абзацев и таблиц
    for item in document.iter_inner_content():
        if isinstance(item, DocxTable):
            markdown = _table_to_markdown(item)
            if markdown:
                stack[-1].blocks.append(Block(type=BlockType.TABLE, text=markdown))
            continue
        if not isinstance(item, DocxParagraph):
            continue
        text = item.text.strip()
        if not text:
            continue
        level = _heading_level(item)
        if level is not None:
            section = Section(heading=text, level=level)
            while len(stack) > 1 and stack[-1].level >= level:
                stack.pop()
            stack[-1].children.append(section)
            stack.append(section)
        else:
            stack[-1].blocks.append(Block(type=BlockType.PARAGRAPH, text=text))

    return DocumentIR(title=title, source_type="upload", root=root, meta={"format": "docx"})
