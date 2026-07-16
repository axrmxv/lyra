"""Раннер offline-evals: прогон датасета через настоящий RAG-граф.

evals — оркестрирующий слой уровня workers: зовёт rag/retrieval напрямую.
temperature=0 гарантируют LLM-клиенты; judge выбирается конфигом/флагом.
Каждый run пишет config_snapshot — без него результат бесполезен для
регресс-анализа (.claude/rules/evals.md).
"""

import json
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import structlog

from lyra.core.clients.llm import LLMClient, LLMUnavailable
from lyra.core.config import Settings, get_settings
from lyra.core.constants import DEFAULT_TENANT_ID
from lyra.db.models import EvalItem, EvalRunStatus
from lyra.db.repositories import CollectionRepository, EvalRepository
from lyra.db.session import get_sessionmaker
from lyra.evals.dataset import DatasetItem, load_jsonl, sync_dataset
from lyra.evals.gate import (
    GateResult,
    baseline_deltas,
    evaluate_gate,
    load_baseline,
    load_thresholds,
)
from lyra.evals.judge import Judge, build_judge_llm
from lyra.evals.metrics import (
    ItemScores,
    aggregate,
    citation_validity,
    context_precision_score,
    context_recall,
    hit_at_k,
    paraphrase_spread,
)
from lyra.evals.prompts import judge_prompt_versions
from lyra.evals.report import build_json_report, build_markdown_report, write_reports
from lyra.evals.seed import DEMO_COLLECTION_NAME
from lyra.rag.prompts import prompt_versions
from lyra.rag.service import answer_question, build_deps
from lyra.retrieval.interfaces import SearchFilters
from lyra.retrieval.retriever import HybridRetriever

logger = structlog.get_logger(__name__)


class RunSummary:
    def __init__(
        self,
        run_id: uuid.UUID,
        aggregates: dict[str, Any],
        gate: GateResult,
        json_path: Path,
        md_path: Path,
    ) -> None:
        self.run_id = run_id
        self.aggregates = aggregates
        self.gate = gate
        self.json_path = json_path
        self.md_path = md_path


def _git_ref() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return out.stdout.strip() or None
    except OSError:
        return None


def _config_snapshot(
    settings: Settings,
    *,
    judge_model: str,
    judge_provider: str,
    chunking_config: dict[str, Any],
    unreviewed_used: bool,
) -> dict[str, Any]:
    return {
        "generation_model": settings.generation_model,
        "grading_model": settings.grading_model,
        "judge_model": judge_model,
        "judge_provider": judge_provider,
        "prompts": prompt_versions(),
        "judge_prompts": judge_prompt_versions(),
        "retrieval": {
            "rag_top_k": settings.rag_top_k,
            "rerank_top_n": settings.rerank_top_n,
            "sufficiency_min_candidates": settings.sufficiency_min_candidates,
            "sufficiency_min_rerank_score": settings.sufficiency_min_rerank_score,
            "sufficiency_auto_accept_score": settings.sufficiency_auto_accept_score,
        },
        "chunking_config": chunking_config,
        "unreviewed_used": unreviewed_used,
    }


async def _score_item(
    *,
    jsonl_item: DatasetItem,
    db_item: EvalItem,
    judge: Judge,
    llm: LLMClient | None,
    retriever: HybridRetriever | None,
    settings: Settings,
    collection_id: uuid.UUID,
    trace_id: str,
) -> tuple[ItemScores, dict[str, Any], dict[str, Any]]:
    """Прогон одного item: (метрики, payload-данные для record, judge_raw)."""
    structlog.contextvars.bind_contextvars(trace_id=trace_id)
    try:
        maker = get_sessionmaker()
        deps = build_deps(settings, maker, llm=llm, retriever=retriever)
        started = time.monotonic()
        payload, state = await answer_question(
            jsonl_item.question,
            tenant_id=DEFAULT_TENANT_ID,
            deps=deps,
            collection_id=collection_id,
        )
        took_ms = int((time.monotonic() - started) * 1000)

        expected_doc_ids = {uuid.UUID(d) for d in (db_item.expected_doc_ids or [])}
        retrieved_doc_ids = [chunk.document_id for chunk in state.retrieved_chunks]

        scores = ItemScores(
            item_id=jsonl_item.id,
            kind=jsonl_item.kind.value,
            subset=jsonl_item.subset,
            paraphrase_group=jsonl_item.paraphrase_group,
            refusal=payload.refusal,
            llm_calls=payload.usage.llm_calls,
            took_ms=took_ms,
            corrective_iterations=state.corrective_iterations,
            generate_retries=state.generate_retries,
            trace_id=trace_id,
            answer=payload.answer,
        )
        judge_raw: dict[str, Any] = {}

        scores.context_recall = context_recall(expected_doc_ids, retrieved_doc_ids)
        k = settings.rag_top_k
        scores.hit_at_k_post_rerank = hit_at_k(expected_doc_ids, retrieved_doc_ids, k)
        if expected_doc_ids:
            # hit@k до rerank — отдельный retrieval-вызов (быстрый, без cross-encoder)
            pre = await deps.retriever.retrieve(
                state.condensed_question or jsonl_item.question,
                tenant_id=DEFAULT_TENANT_ID,
                filters=SearchFilters(collection_id=collection_id),
                top_k=k,
                rerank=False,
            )
            scores.hit_at_k_pre_rerank = hit_at_k(
                expected_doc_ids, [chunk.document_id for chunk in pre.chunks], k
            )

        if not payload.refusal and jsonl_item.kind.value in ("answerable", "paraphrase"):
            context_text = "\n\n".join(chunk.text for chunk in state.context_chunks)
            verdict = await judge.faithfulness(payload.answer, context_text)
            judge_raw["faithfulness"] = verdict.model_dump()
            if verdict.claims:
                scores.faithfulness = sum(1 for claim in verdict.claims if claim.supported) / len(
                    verdict.claims
                )
            scores.answer_relevance = await judge.answer_relevance(
                jsonl_item.question, payload.answer
            )
            scores.context_precision = await context_precision_score(
                judge, jsonl_item.question, jsonl_item.ground_truth_answer, state.context_chunks
            )
            scores.citation_validity = await citation_validity(
                judge, payload.answer, payload.citations, state.context_chunks
            )
        elif payload.refusal and jsonl_item.kind.value in ("answerable", "paraphrase"):
            # Ложный отказ: релевантность нулевая по определению
            scores.answer_relevance = 0.0

        record_payload = {
            "answer": payload.answer,
            "citations": [c.model_dump(mode="json") for c in payload.citations],
        }
        return scores, record_payload, judge_raw
    finally:
        structlog.contextvars.unbind_contextvars("trace_id")


async def run_evals(
    *,
    dataset_name: str = "golden",
    dataset_path: Path,
    thresholds_path: Path,
    baseline_path: Path,
    output_dir: Path,
    judge_provider: str | None = None,
    limit: int | None = None,
    reviewed_only: bool = False,
    update_baseline: bool = False,
    llm: LLMClient | None = None,
    judge_llm: LLMClient | None = None,
    retriever: HybridRetriever | None = None,
    run_id: uuid.UUID | None = None,
) -> RunSummary:
    """Полный конвейер: синк датасета → прогон → метрики → отчёты → гейт.

    llm/judge_llm внедряются в тестах (FakeLLM); run_id — при запуске из
    Celery-задачи, когда run создан заранее эндпоинтом."""
    settings = get_settings()
    tenant_id = DEFAULT_TENANT_ID
    maker = get_sessionmaker()

    jsonl_items = load_jsonl(dataset_path)
    if reviewed_only:
        jsonl_items = [item for item in jsonl_items if item.reviewed]
        if not jsonl_items:
            raise ValueError("Нет reviewed-item'ов: гейт по неотревьюенному датасету запрещён")
    unreviewed_used = any(not item.reviewed for item in jsonl_items)
    if limit is not None:
        jsonl_items = jsonl_items[:limit]

    if judge_llm is None:
        judge_llm, judge_model = build_judge_llm(settings, judge_provider)
    else:
        judge_model = "injected"
    judge = Judge(judge_llm)

    async with maker() as session:
        dataset_id, item_mapping = await sync_dataset(
            session, dataset_name=dataset_name, items=jsonl_items
        )
        collection = await CollectionRepository(session).get_by_name(
            tenant_id, DEMO_COLLECTION_NAME
        )
        if collection is None:
            raise ValueError(
                "Демо-коллекция не найдена — выполните сид корпуса (python -m lyra.evals seed)"
            )
        snapshot = _config_snapshot(
            settings,
            judge_model=judge_model,
            judge_provider=judge_provider or settings.judge_provider,
            chunking_config=dict(collection.chunking_config),
            unreviewed_used=unreviewed_used,
        )
        evals = EvalRepository(session)
        if run_id is None:
            run = await evals.create_run(
                tenant_id, dataset_id=dataset_id, git_ref=_git_ref(), config_snapshot=snapshot
            )
            run_id = run.id
        await evals.update_run(
            tenant_id,
            run_id,
            status=EvalRunStatus.RUNNING,
            config_snapshot=snapshot,
            git_ref=_git_ref(),
        )
        await session.commit()
        collection_id = collection.id
    assert run_id is not None

    all_scores: list[ItemScores] = []
    for index, jsonl_item in enumerate(jsonl_items, start=1):
        trace_id = f"tr_eval_{run_id.hex[:8]}_{jsonl_item.id}"
        logger.info("eval_item_start", item=jsonl_item.id, index=index, total=len(jsonl_items))
        try:
            scores, record_payload, judge_raw = await _score_item(
                jsonl_item=jsonl_item,
                db_item=item_mapping[jsonl_item.id],
                judge=judge,
                llm=llm,
                retriever=retriever,
                settings=settings,
                collection_id=collection_id,
                trace_id=trace_id,
            )
        except LLMUnavailable as exc:
            # Сбой LLM/judge одного item не роняет весь прогон: item
            # фиксируется без метрик (None), гейт честно краснеет
            # «метрика не посчитана» при массовых сбоях
            logger.error("eval_item_failed", item=jsonl_item.id, error=str(exc))
            scores = ItemScores(
                item_id=jsonl_item.id,
                kind=jsonl_item.kind.value,
                subset=jsonl_item.subset,
                paraphrase_group=jsonl_item.paraphrase_group,
                refusal=False,
                trace_id=trace_id,
            )
            record_payload = {"answer": None, "citations": None}
            judge_raw = {"error": str(exc)}
        all_scores.append(scores)
        async with maker() as session:
            await EvalRepository(session).add_record(
                tenant_id,
                run_id=run_id,
                item_id=item_mapping[jsonl_item.id].id,
                answer=record_payload["answer"],
                citations=record_payload["citations"],
                metrics=scores.model_dump(exclude={"answer"}),
                judge_raw=judge_raw or None,
            )
            await session.commit()

    aggregates = aggregate(all_scores)
    spreads = paraphrase_spread(all_scores)
    thresholds = load_thresholds(thresholds_path)
    baseline = load_baseline(baseline_path)
    gate = evaluate_gate(aggregates, thresholds, baseline)
    deltas = baseline_deltas(aggregates, baseline)

    async with maker() as session:
        await EvalRepository(session).update_run(
            tenant_id,
            run_id,
            status=EvalRunStatus.COMPLETED,
            aggregate={**aggregates, "gate_passed": gate.passed, "baseline_delta": deltas},
        )
        await session.commit()

    json_report = build_json_report(
        run_id=str(run_id),
        aggregates=aggregates,
        gate=gate,
        deltas=deltas,
        scores=all_scores,
        spreads=spreads,
        config_snapshot=snapshot,
        unreviewed_used=unreviewed_used,
    )
    markdown = build_markdown_report(
        run_id=str(run_id),
        aggregates=aggregates,
        gate=gate,
        thresholds=thresholds,
        deltas=deltas,
        scores=all_scores,
        spreads=spreads,
        unreviewed_used=unreviewed_used,
    )
    json_path, md_path = write_reports(output_dir, json_report, markdown)

    if update_baseline:
        baseline_path.write_text(json_report_baseline(json_report), encoding="utf-8")
        logger.info("baseline_updated", path=str(baseline_path))

    logger.info(
        "eval_run_finished",
        run_id=str(run_id),
        gate_passed=gate.passed,
        metrics=aggregates,
    )
    return RunSummary(run_id, aggregates, gate, json_path, md_path)


def json_report_baseline(json_report: dict[str, Any]) -> str:
    """Baseline-артефакт: только метрики и идентификация run'а."""
    return json.dumps(
        {
            "run_id": json_report["run_id"],
            "metrics": json_report["metrics"],
            "config_snapshot": {
                "generation_model": json_report["config_snapshot"]["generation_model"],
                "judge_model": json_report["config_snapshot"]["judge_model"],
                "prompts": json_report["config_snapshot"]["prompts"],
            },
        },
        ensure_ascii=False,
        indent=2,
    )
