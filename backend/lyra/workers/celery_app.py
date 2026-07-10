"""Celery-приложение: брокер Redis, очереди ingest/sync/evals (ADR-008).

acks_late=True — задача не теряется при смерти воркера; обратная сторона:
каждая задача обязана быть идемпотентной (.claude/rules/api.md).
"""

from celery import Celery
from kombu import Queue

from lyra.core.config import get_settings

settings = get_settings()

celery_app = Celery("lyra", broker=settings.redis_url)

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
)


@celery_app.task(name="lyra.ping")  # type: ignore[untyped-decorator]  # у celery нет стабов
def ping() -> str:
    """Демо-задача для проверки связки API → брокер → worker."""
    return "pong"
