"""Диспетчер парсеров и определение формата по содержимому (magic bytes).

Формат определяется по содержимому, не по расширению (docs/security §7):
расширение — только подсказка внутри текстовых форматов (md или txt).
"""

import codecs
import os

from lyra.ingest.ir import DocumentIR

SUPPORTED_FORMATS = ("pdf", "docx", "markdown", "txt")

# Белый список текстовых расширений: всё, что декодируется в UTF-8, но названо
# иначе, не наш формат (SUPPORTED_FORMATS) и до парсера не доходит
_TEXT_EXTENSIONS = {
    "": "txt",
    ".txt": "txt",
    ".text": "txt",
    ".md": "markdown",
    ".markdown": "markdown",
}


class ParserError(Exception):
    """Permanent-ошибка парсинга: не ретраится (ADR-008)."""


def _is_utf8_prefix(content: bytes) -> bool:
    """UTF-8 ли буфер, который может обрываться на середине символа.

    detect_format вызывается на голове файла (upload, reindex), поэтому
    незавершённая хвостовая последовательность — не признак чужой кодировки:
    инкрементальный декодер буферизует её вместо UnicodeDecodeError.
    """
    try:
        codecs.getincrementaldecoder("utf-8")().decode(content, final=False)
    except UnicodeDecodeError:
        return False
    return True


def detect_format(content: bytes, filename: str) -> str | None:
    """pdf | docx | markdown | txt | None (не поддержан).

    content — файл целиком или его начало (достаточно первых килобайт).
    """
    if content.startswith(b"%PDF-"):
        return "pdf"
    if content.startswith(b"PK\x03\x04"):
        # zip-контейнер: docx только если заявлен расширением, иначе не рискуем
        return "docx" if filename.lower().endswith(".docx") else None
    if not _is_utf8_prefix(content):
        return None
    return _TEXT_EXTENSIONS.get(os.path.splitext(filename)[1].lower())


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
