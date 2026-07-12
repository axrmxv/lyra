"""Клиенты внешних сервисов: единая точка таймаутов, retry и трейсинга.

HTTP-вызовы к Ollama/TEI/Confluence по месту использования запрещены
(.claude/rules/python.md) — только через классы этого пакета.
"""

from lyra.core.clients.embeddings import EmbeddingClient

__all__ = ["EmbeddingClient"]
