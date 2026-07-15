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
