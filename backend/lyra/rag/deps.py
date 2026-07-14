"""Зависимости узлов графа: retriever и LLM внедряются, узлы их не создают."""

from dataclasses import dataclass

from lyra.core.clients.llm import LLMClient
from lyra.core.config import Settings
from lyra.retrieval.retriever import HybridRetriever


@dataclass
class GraphDeps:
    retriever: HybridRetriever
    llm: LLMClient
    settings: Settings
