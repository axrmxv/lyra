"""Парсеры форматов → DocumentIR. Диспетчеризация по формату — parse_document."""

from lyra.ingest.parsers.base import ParserError, detect_format, parse_document

__all__ = ["ParserError", "detect_format", "parse_document"]
