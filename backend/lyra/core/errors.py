"""Доменные ошибки и единый формат ответа об ошибке (docs/api-contract.md).

Формат: {"error": {"code": ..., "message": ..., "details": {}}}.
Сервисы поднимают LyraError-подклассы; HTTP-маппинг — в обработчиках app.py.
"""

from typing import Any


class LyraError(Exception):
    code = "internal_error"
    status_code = 500

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(LyraError):
    code = "not_found"
    status_code = 404


class UnauthorizedError(LyraError):
    code = "unauthorized"
    status_code = 401


class ForbiddenError(LyraError):
    code = "forbidden"
    status_code = 403


class ConflictError(LyraError):
    code = "conflict"
    status_code = 409


class InvalidSourceConfigError(LyraError):
    """config источника не соответствует форме своего типа (api-contract §2)."""

    code = "invalid_source_config"
    status_code = 400


class SecretInConfigError(LyraError):
    """В config источника нашёлся секрет: только token_secret_ref на env."""

    code = "secret_in_config"
    status_code = 400


class PayloadTooLargeError(LyraError):
    """Загружаемый файл больше upload_max_bytes (api-contract §2)."""

    code = "payload_too_large"
    status_code = 413


class UnsupportedFileTypeError(LyraError):
    """Формат файла не входит в SUPPORTED_FORMATS (api-contract §2)."""

    code = "unsupported_file_type"
    status_code = 415


class ServiceUnavailableError(LyraError):
    """Зависимость недоступна (брокер, LLM) — честная 503 (architecture §4)."""

    code = "service_unavailable"
    status_code = 503


class RateLimitError(LyraError):
    """429 c Retry-After (api-contract, преамбула; nfr §2)."""

    code = "rate_limited"
    status_code = 429

    def __init__(self, message: str, *, retry_after_s: int) -> None:
        super().__init__(message, details={"retry_after_s": retry_after_s})
        self.retry_after_s = retry_after_s


class OverloadedError(RateLimitError):
    """Семафор одновременных генераций занят — тоже 429, но свой code."""

    code = "overloaded"
