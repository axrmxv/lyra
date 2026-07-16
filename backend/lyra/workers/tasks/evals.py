"""Celery-задача eval-run (очередь evals, ADR-008; api-contract §6).

Задача идемпотентна на уровне run: повтор перезапускает прогон того же
run_id (records добавляются заново, aggregate перезаписывается) — для
offline-evals это безопасно.
"""

import asyncio
import uuid
from pathlib import Path

import structlog

from lyra.core.config import get_settings
from lyra.core.constants import DEFAULT_TENANT_ID
from lyra.db.models import EvalRunStatus
from lyra.db.repositories import EvalRepository
from lyra.db.session import get_engine, get_sessionmaker
from lyra.evals.runner import run_evals
from lyra.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(name="lyra.evals.run", queue="evals")  # type: ignore[untyped-decorator]  # у celery нет стабов
def run_evals_task(run_id: str, dataset_name: str, judge_provider: str | None = None) -> str:
    """Прогон evals в воркере; run создан заранее эндпоинтом (status=queued)."""
    settings = get_settings()
    evals_dir = Path(settings.evals_dir)

    async def runner() -> str:
        # Кэшированные engine/sessionmaker привязаны к чужому event loop
        # (каждая Celery-задача создаёт свой через asyncio.run) — сбрасываем
        get_engine.cache_clear()
        get_sessionmaker.cache_clear()
        try:
            summary = await run_evals(
                dataset_name=dataset_name,
                dataset_path=evals_dir / "datasets" / f"{dataset_name}.jsonl",
                thresholds_path=evals_dir / "thresholds.yaml",
                baseline_path=evals_dir / "baseline.json",
                output_dir=evals_dir / "reports",
                judge_provider=judge_provider,
                run_id=uuid.UUID(run_id),
            )
            return "passed" if summary.gate.passed else "failed_gate"
        except Exception as exc:
            logger.exception("eval_run_failed", run_id=run_id)
            maker = get_sessionmaker()
            async with maker() as session:
                await EvalRepository(session).update_run(
                    DEFAULT_TENANT_ID,
                    uuid.UUID(run_id),
                    status=EvalRunStatus.FAILED,
                    aggregate={"error": str(exc)},
                )
                await session.commit()
            raise
        finally:
            await get_engine().dispose()
            get_engine.cache_clear()
            get_sessionmaker.cache_clear()

    return asyncio.run(runner())
