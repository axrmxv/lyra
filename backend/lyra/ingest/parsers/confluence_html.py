"""Confluence storage-HTML → DocumentIR: h1-h4, таблицы, код-макросы.

Storage format — XHTML c макросами <ac:structured-macro>; макрос code
разворачивается в код-блок, прочие макросы — в их текстовое содержимое.
"""

from bs4 import BeautifulSoup, Tag

from lyra.ingest.ir import Block, BlockType, DocumentIR, Section


def _table_to_markdown(table: Tag) -> str:
    rows = []
    for tr in table.find_all("tr"):
        cells = [
            cell.get_text(" ", strip=True).replace("|", "\\|") for cell in tr.find_all(["th", "td"])
        ]
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * len(rows[0])]
    lines += ["| " + " | ".join(row) + " |" for row in rows[1:]]
    return "\n".join(lines)


def parse_confluence_html(html: str, *, title: str) -> DocumentIR:
    soup = BeautifulSoup(html, "lxml")
    root = Section()
    stack: list[Section] = [root]

    def emit(element: Tag) -> None:
        name = element.name or ""
        if name in ("h1", "h2", "h3", "h4"):
            level = int(name[1])
            section = Section(heading=element.get_text(" ", strip=True), level=level)
            while len(stack) > 1 and stack[-1].level >= level:
                stack.pop()
            stack[-1].children.append(section)
            stack.append(section)
        elif name == "table":
            markdown = _table_to_markdown(element)
            if markdown:
                stack[-1].blocks.append(Block(type=BlockType.TABLE, text=markdown))
        elif name == "ac:structured-macro" and element.get("ac:name") == "code":
            body = element.find("ac:plain-text-body")
            lang_param = element.find("ac:parameter", {"ac:name": "language"})
            code = body.get_text() if body else ""
            if code.strip():
                stack[-1].blocks.append(
                    Block(
                        type=BlockType.CODE,
                        text=code,
                        meta={"lang": lang_param.get_text() if lang_param else ""},
                    )
                )
        elif name in ("ul", "ol"):
            items = [
                "- " + li.get_text(" ", strip=True)
                for li in element.find_all("li", recursive=False)
            ]
            if items:
                stack[-1].blocks.append(Block(type=BlockType.LIST, text="\n".join(items)))
        elif name == "p":
            text = element.get_text(" ", strip=True)
            if text:
                stack[-1].blocks.append(Block(type=BlockType.PARAGRAPH, text=text))
        else:
            # Контейнеры (div, макросы-панели): обходим детей
            for child in element.find_all(recursive=False):
                emit(child)

    body_root = soup.body or soup
    for child in body_root.find_all(recursive=False):
        emit(child)

    return DocumentIR(
        title=title, source_type="confluence", root=root, meta={"format": "confluence"}
    )
