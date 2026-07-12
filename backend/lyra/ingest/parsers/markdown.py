"""Markdown → DocumentIR: заголовки #..####, код-блоки, таблицы, front-matter."""

import re
from typing import Any

import yaml

from lyra.ingest.ir import Block, BlockType, DocumentIR, Section

_HEADING = re.compile(r"^(#{1,4})\s+(.*)$")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_FENCE = re.compile(r"^```(\w*)\s*$")


def _split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            try:
                meta = yaml.safe_load(text[4:end]) or {}
                if isinstance(meta, dict):
                    return meta, text[end + 4 :]
            except yaml.YAMLError:
                pass
    return {}, text


def parse_markdown(text: str, *, title: str) -> DocumentIR:
    front_matter, body = _split_front_matter(text)
    root = Section()
    # Стек секций по уровню заголовков; блоки копятся в текущую
    stack: list[Section] = [root]
    paragraph_lines: list[str] = []
    table_lines: list[str] = []
    code_lines: list[str] = []
    code_lang = ""
    in_code = False

    def flush_paragraph() -> None:
        nonlocal paragraph_lines
        joined = "\n".join(paragraph_lines).strip()
        if joined:
            block_type = (
                BlockType.LIST
                if all(re.match(r"^\s*([-*+]|\d+\.)\s", ln) for ln in paragraph_lines if ln.strip())
                else BlockType.PARAGRAPH
            )
            stack[-1].blocks.append(Block(type=block_type, text=joined))
        paragraph_lines = []

    def flush_table() -> None:
        nonlocal table_lines
        if table_lines:
            stack[-1].blocks.append(Block(type=BlockType.TABLE, text="\n".join(table_lines)))
            table_lines = []

    for line in body.splitlines():
        fence = _FENCE.match(line)
        if fence and not in_code:
            flush_paragraph()
            flush_table()
            in_code, code_lang, code_lines = True, fence.group(1), []
            continue
        if line.startswith("```") and in_code:
            stack[-1].blocks.append(
                Block(type=BlockType.CODE, text="\n".join(code_lines), meta={"lang": code_lang})
            )
            in_code = False
            continue
        if in_code:
            code_lines.append(line)
            continue

        heading = _HEADING.match(line)
        if heading:
            flush_paragraph()
            flush_table()
            level = len(heading.group(1))
            section = Section(heading=heading.group(2).strip(), level=level)
            while len(stack) > 1 and stack[-1].level >= level:
                stack.pop()
            stack[-1].children.append(section)
            stack.append(section)
            continue

        if _TABLE_ROW.match(line):
            flush_paragraph()
            table_lines.append(line.strip())
            continue
        flush_table()

        if line.strip():
            paragraph_lines.append(line)
        else:
            flush_paragraph()

    flush_paragraph()
    flush_table()
    if in_code and code_lines:  # незакрытый fence — не теряем содержимое
        root.blocks.append(Block(type=BlockType.CODE, text="\n".join(code_lines)))

    doc_title = str(front_matter.get("title", title))
    return DocumentIR(
        title=doc_title,
        source_type="upload",
        root=root,
        meta={"format": "markdown", "front_matter": front_matter},
    )
