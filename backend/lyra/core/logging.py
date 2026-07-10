"""Структурные логи: structlog с JSON-выводом и контекстными переменными.

Чувствительные поля маскируются процессором _mask_sensitive — правило
docs/security-and-access.md §5: секреты в логи не попадают.
"""

import logging

import structlog
from structlog.typing import EventDict, WrappedLogger

SENSITIVE_KEYS = frozenset({"password", "token", "secret", "authorization", "api_key"})

_MASK = "***"


def _mask_sensitive(
    _logger: WrappedLogger,
    _method: str,
    event_dict: EventDict,
) -> EventDict:
    for key in event_dict:
        if any(marker in key.lower() for marker in SENSITIVE_KEYS):
            event_dict[key] = _MASK
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _mask_sensitive,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        cache_logger_on_first_use=True,
    )
