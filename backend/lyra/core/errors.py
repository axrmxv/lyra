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
