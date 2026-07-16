"""Celery-приложение: брокер Redis, очереди ingest/sync/evals (ADR-008).

acks_late=True — задача не теряется при смерти воркера; обратная сторона:
каждая задача обязана быть идемпотентной (.claude/rules/api.md).
"""

from celery import Celery
from kombu import Queue

from lyra.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "lyra",
    broker=settings.redis_url,
    include=["lyra.workers.tasks.ingest", "lyra.workers.tasks.evals"],
)

celery_app.conf.update(
    task_acks_late=True,
    task_default_queue="ingest",
    task_queues=(
        Queue("ingest"),
        Queue("sync"),
        Queue("evals"),
    ),
    broker_connection_retry_on_startup=True,
    worker_prefetch_multiplier=1,
    # Redis-брокер: unacked-задача погибшего воркера редоставляется через
    # visibility_timeout. Дефолт 1ч → восстановление после SIGKILL слишком
    # долгое; 600с безопасно, пока любая задача короче 10 минут
    broker_transport_options={"visibility_timeout": 600},
    beat_schedule={
        # Тик раз в минуту; каждый источник сам решает по своему cron (croniter)
        "sync-due-sources": {"task": "lyra.ingest.sync_due_sources", "schedule": 60.0},
        # Отложенная чистка chunks у superseded-версий (data-model §3)
        "gc-superseded": {"task": "lyra.ingest.gc_superseded", "schedule": 3600.0},
    },
)


@celery_app.task(name="lyra.ping")  # type: ignore[untyped-decorator]  # у celery нет стабов
def ping() -> str:
    """Демо-задача для проверки связки API → брокер → worker."""
    return "pong"
