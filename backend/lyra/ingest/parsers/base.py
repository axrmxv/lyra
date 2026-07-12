"""Диспетчер парсеров и определение формата по содержимому (magic bytes).

Формат определяется по содержимому, не по расширению (docs/security §7):
расширение — только подсказка для текстовых форматов.
"""

from lyra.ingest.ir import DocumentIR

SUPPORTED_FORMATS = ("pdf", "docx", "markdown", "txt")


class ParserError(Exception):
    """Permanent-ошибка парсинга: не ретраится (ADR-008)."""


def detect_format(content: bytes, filename: str) -> str | None:
    """pdf | docx | markdown | txt | None (не поддержан)."""
    if content.startswith(b"%PDF-"):
        return "pdf"
    if content.startswith(b"PK\x03\x04") and filename.lower().endswith(".docx"):
        return "docx"
    if content.startswith(b"PK\x03\x04"):
        return None  # zip, но не заявлен docx — не рискуем
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if filename.lower().endswith((".md", ".markdown")):
        return "markdown"
    if filename.lower().endswith(".txt") or not filename.lower().endswith((".exe", ".bin", ".zip")):
        return "txt"
    return None


def parse_document(content: bytes, *, fmt: str, title: str) -> DocumentIR:
    # Импорты внутри диспетчера: pymupdf/docx тяжёлые, нужны только своему формату
    if fmt == "pdf":
        from lyra.ingest.parsers.pdf import parse_pdf

        return parse_pdf(content, title=title)
    if fmt == "docx":
        from lyra.ingest.parsers.docx import parse_docx

        return parse_docx(content, title=title)
    if fmt == "markdown":
        from lyra.ingest.parsers.markdown import parse_markdown

        return parse_markdown(content.decode("utf-8"), title=title)
    if fmt == "txt":
        from lyra.ingest.parsers.txt import parse_txt

        return parse_txt(content.decode("utf-8"), title=title)
    if fmt == "confluence":
        from lyra.ingest.parsers.confluence_html import parse_confluence_html

        return parse_confluence_html(content.decode("utf-8"), title=title)
    raise ParserError(f"Неподдерживаемый формат: {fmt}")
