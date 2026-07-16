"""Интеграционный тест eval-конвейера: мини-датасет → run → records → отчёт.

Живой postgres; граф и judge — на фейках (без Ollama/TEI).
"""

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from lyra.core.clients.llm import LLMResult, LLMUnavailable, Message
from lyra.core.config import Settings, get_settings
from lyra.core.constants import DEFAULT_TENANT_ID
from lyra.db.models import (
    Collection,
    Document,
    EvalDataset,
    EvalItem,
    EvalRecord,
    EvalRun,
    Source,
    SourceType,
)
from lyra.db.session import get_engine, get_sessionmaker
from lyra.evals.judge import (
    ChunkRelevanceVerdict,
    CitationSupportVerdict,
    ClaimVerdict,
    FaithfulnessVerdict,
    RelevanceVerdict,
)
from lyra.evals.runner import run_evals
from lyra.evals.seed import DEMO_COLLECTION_NAME
from lyra.rag.state import SelfCheckResult, Sufficiency
from lyra.retrieval.interfaces import ScoredChunk
from tests.rag_fakes import FakeLLM, FakeRetriever, make_chunk

pytestmark = pytest.mark.integration

T = TypeVar("T", bound=BaseModel)

THRESHOLDS = Path(__file__).parents[2] / "evals" / "thresholds.yaml"


class StubJudgeLLM:
    """Judge-фейк: вердикт по типу схемы, независимо от числа вызовов."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def chat(self, messages: list[Message], **kwargs: Any) -> LLMResult:
        raise AssertionError("judge использует только structured")

    def chat_stream(self, messages: list[Message], **kwargs: Any) -> Any:
        raise AssertionError("judge не стримит")

    async def structured(
        self, messages: list[Message], schema: type[T], *, node: str, model_role: str = "grading"
    ) -> tuple[T, LLMResult]:
        self.calls.append(node)
        result = LLMResult(text="{}", prompt_tokens=5, completion_tokens=5)
        if schema is FaithfulnessVerdict:
            verdict: BaseModel = FaithfulnessVerdict(
                claims=[ClaimVerdict(claim="факт", supported=True)]
            )
        elif schema is RelevanceVerdict:
            verdict = RelevanceVerdict(score=0.9, reasoning="ок")
        elif schema is ChunkRelevanceVerdict:
            verdict = ChunkRelevanceVerdict(relevant=True)
        elif schema is CitationSupportVerdict:
            verdict = CitationSupportVerdict(supported=True)
        else:
            raise AssertionError(f"Неожиданная схема judge: {schema}")
        # verdict создан по конкретной схеме выше — тип совпадает с T
        return verdict, result  # type: ignore[return-value]


@pytest.fixture()
async def demo_env(migrated_db: Settings) -> AsyncIterator[dict[str, Any]]:
    """Демо-коллекция + 2 документа корпуса; чистка вместе с eval-таблицами."""
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    dsn = migrated_db.database_dsn.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(dsn)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        collection = Collection(
            tenant_id=DEFAULT_TENANT_ID, name=DEMO_COLLECTION_NAME, embedding_model="bge-m3"
        )
        session.add(collection)
        await session.flush()
        source = Source(
            tenant_id=DEFAULT_TENANT_ID,
            collection_id=collection.id,
            type=SourceType.UPLOAD,
            name="demo",
        )
        session.add(source)
        await session.flush()
        documents = []
        for name in ("doc-a.md", "doc-b.md"):
            document = Document(
                tenant_id=DEFAULT_TENANT_ID,
                source_id=source.id,
                external_id=name,
                title=name,
            )
            session.add(document)
            documents.append(document)
        await session.commit()
        env = {
            "collection_id": collection.id,
            "doc_ids": {d.external_id: d.id for d in documents},
        }
    yield env
    async with maker() as session:
        await session.execute(delete(EvalRecord))
        await session.execute(delete(EvalRun))
        await session.execute(delete(EvalItem))
        await session.execute(delete(EvalDataset))
        await session.execute(delete(Document).where(Document.source_id == source.id))
        await session.execute(delete(Source).where(Source.id == source.id))
        await session.execute(delete(Collection).where(Collection.id == collection.id))
        await session.commit()
    await get_engine().dispose()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    await engine.dispose()


def _chunks_for(doc_id: uuid.UUID, text: str) -> list[ScoredChunk]:
    chunks = []
    for i in range(4):
        chunk = make_chunk(f"{text}, пункт {i}.", ordinal=i, rerank=0.3)
        chunks.append(replace(chunk, document_id=doc_id))
    return chunks


async def test_eval_pipeline_end_to_end(demo_env: dict[str, Any], tmp_path: Path) -> None:
    doc_a = demo_env["doc_ids"]["doc-a.md"]
    dataset_path = tmp_path / "mini.jsonl"
    items = [
        {
            "id": "mini-1",
            "kind": "answerable",
            "subset": "single_chunk",
            "question": "Сколько дней отпуска?",
            "ground_truth_answer": "31 день",
            "expected_docs": ["doc-a.md"],
            "reviewed": True,
        },
        {
            "id": "mini-2",
            "kind": "answerable",
            "subset": "single_chunk",
            "question": "Какая длина пароля?",
            "ground_truth_answer": "16 символов",
            "expected_docs": ["doc-a.md"],
            "reviewed": True,
        },
        {
            "id": "mini-3",
            "kind": "unanswerable",
            "subset": "unanswerable",
            "question": "Какой размер бонуса?",
            "expected_docs": [],
            "reviewed": True,
        },
    ]
    dataset_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in items), encoding="utf-8"
    )

    good_a = _chunks_for(doc_a, "Отпуск 31 день")
    weak = [make_chunk("нерелевантно")]
    # Порядок: item1 retrieve + pre-rerank, item2 retrieve + pre-rerank,
    # item3 retrieve + 2 corrective (без pre-rerank: разметка пуста)
    retriever = FakeRetriever([good_a, good_a, good_a, good_a, weak, weak, weak])
    graph_llm = FakeLLM(
        chat_responses={
            "generate": ["Отпуск 31 день [1].", "Пароль 16 символов [1]."],
            "corrective_retrieve": ["v2", "v3"],
        },
        structured_responses={
            "grade_sufficiency": [
                Sufficiency(sufficient=True, score=0.9),
                Sufficiency(sufficient=True, score=0.9),
            ],
            "self_check": [SelfCheckResult(passed=True), SelfCheckResult(passed=True)],
        },
    )
    judge_llm = StubJudgeLLM()

    summary = await run_evals(
        dataset_name="mini",
        dataset_path=dataset_path,
        thresholds_path=THRESHOLDS,
        baseline_path=tmp_path / "baseline.json",
        output_dir=tmp_path / "reports",
        llm=graph_llm,
        judge_llm=judge_llm,
        retriever=retriever,  # type: ignore[arg-type]
    )

    assert summary.gate.passed, summary.gate.failures
    assert summary.aggregates["faithfulness"] == 1.0
    assert summary.aggregates["answer_relevance"] == 0.9
    assert summary.aggregates["citation_validity"] == 1.0
    assert summary.aggregates["context_recall"] == 1.0
    assert summary.aggregates["honest_refusal_rate"] == 1.0
    assert summary.aggregates["false_refusal_rate"] == 0.0
    assert summary.aggregates["items_total"] == 3

    # Персистенция: run completed, 3 records с метриками
    maker = get_sessionmaker()
    async with maker() as session:
        from lyra.db.repositories import EvalRepository

        repo = EvalRepository(session)
        run = await repo.get_run(DEFAULT_TENANT_ID, summary.run_id)
        assert run is not None and run.status.value == "completed"
        assert run.config_snapshot["prompts"]  # версии промптов в snapshot
        records = await repo.list_records(DEFAULT_TENANT_ID, summary.run_id)
        assert len(records) == 3

    # Отчёты записаны
    assert summary.json_path.exists() and summary.md_path.exists()
    report = json.loads(summary.json_path.read_text(encoding="utf-8"))
    assert report["gate"]["passed"] is True
    assert len(report["items"]) == 3
    assert "Eval-run" in summary.md_path.read_text(encoding="utf-8")

    # Повторный прогон — второй run, метрики стабильны (детерминированные фейки)
    graph_llm2 = FakeLLM(
        chat_responses={
            "generate": ["Отпуск 31 день [1].", "Пароль 16 символов [1]."],
            "corrective_retrieve": ["v2", "v3"],
        },
        structured_responses={
            "grade_sufficiency": [
                Sufficiency(sufficient=True, score=0.9),
                Sufficiency(sufficient=True, score=0.9),
            ],
            "self_check": [SelfCheckResult(passed=True), SelfCheckResult(passed=True)],
        },
    )
    retriever2 = FakeRetriever([good_a, good_a, good_a, good_a, weak, weak, weak])
    summary2 = await run_evals(
        dataset_name="mini",
        dataset_path=dataset_path,
        thresholds_path=THRESHOLDS,
        baseline_path=tmp_path / "baseline.json",
        output_dir=tmp_path / "reports2",
        llm=graph_llm2,
        judge_llm=StubJudgeLLM(),
        retriever=retriever2,  # type: ignore[arg-type]
    )
    assert summary2.run_id != summary.run_id
    for metric in ("faithfulness", "answer_relevance", "context_recall"):
        assert summary2.aggregates[metric] == summary.aggregates[metric]


class UnavailableJudgeLLM(StubJudgeLLM):
    """Judge, у которого недоступна LLM: каждый structured падает."""

    async def structured(
        self, messages: list[Message], schema: type[T], *, node: str, model_role: str = "grading"
    ) -> tuple[T, LLMResult]:
        raise LLMUnavailable("judge endpoint down")


async def test_judge_failure_does_not_abort_run(demo_env: dict[str, Any], tmp_path: Path) -> None:
    """Сбой judge на item не роняет прогон: run завершается, гейт красный."""
    doc_a = demo_env["doc_ids"]["doc-a.md"]
    dataset_path = tmp_path / "mini.jsonl"
    dataset_path.write_text(
        json.dumps(
            {
                "id": "mini-1",
                "kind": "answerable",
                "subset": "single_chunk",
                "question": "Сколько дней отпуска?",
                "ground_truth_answer": "31 день",
                "expected_docs": ["doc-a.md"],
                "reviewed": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    good_a = _chunks_for(doc_a, "Отпуск 31 день")
    retriever = FakeRetriever([good_a, good_a])
    graph_llm = FakeLLM(
        chat_responses={"generate": ["Отпуск 31 день [1]."]},
        structured_responses={
            "grade_sufficiency": [Sufficiency(sufficient=True, score=0.9)],
            "self_check": [SelfCheckResult(passed=True)],
        },
    )
    summary = await run_evals(
        dataset_name="mini-broken",
        dataset_path=dataset_path,
        thresholds_path=THRESHOLDS,
        baseline_path=tmp_path / "baseline.json",
        output_dir=tmp_path / "reports",
        llm=graph_llm,
        judge_llm=UnavailableJudgeLLM(),
        retriever=retriever,  # type: ignore[arg-type]
    )
    assert not summary.gate.passed  # метрики не посчитаны — честно красный
    maker = get_sessionmaker()
    async with maker() as session:
        from lyra.db.repositories import EvalRepository

        repo = EvalRepository(session)
        run = await repo.get_run(DEFAULT_TENANT_ID, summary.run_id)
        assert run is not None and run.status.value == "completed"
        records = await repo.list_records(DEFAULT_TENANT_ID, summary.run_id)
        assert len(records) == 1
        assert records[0].judge_raw == {"error": "judge endpoint down"}
