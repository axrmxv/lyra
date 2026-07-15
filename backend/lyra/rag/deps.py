"""Зависимости узлов графа: retriever и LLM внедряются, узлы их не создают."""

from dataclasses import dataclass, field

from lyra.core.clients.llm import LLMClient
from lyra.core.config import Settings
from lyra.rag.events import EventSink, NullSink
from lyra.retrieval.retriever import HybridRetriever


@dataclass
class GraphDeps:
    retriever: HybridRetriever
    llm: LLMClient
    settings: Settings
    # SSE-события chat-API (фаза 5); NullSink — граф молчит (evals, тесты)
    sink: EventSink = field(default_factory=NullSink)
