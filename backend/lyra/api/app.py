"""FastAPI-приложение LYRA: /health, /health/ready, /metrics.

Бизнес-эндпоинты появляются в фазах 1+. Каждый ответ несёт X-Trace-Id
(docs/api-contract.md, преамбула); trace_id прокинут в structlog-контекст.
"""

import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.exceptions import HTTPException as StarletteHTTPException

from lyra.api import readiness
from lyra.api.routes.admin import router as admin_router
from lyra.api.routes.auth import router as auth_router
from lyra.core.config import get_settings
from lyra.core.errors import LyraError
from lyra.core.logging import configure_logging

logger = structlog.get_logger(__name__)


def _error_body(
    code: str, message: str, details: dict[str, object] | None = None
) -> dict[str, object]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="LYRA", version="0.1.0")

    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(admin_router, prefix="/api/v1")

    @app.exception_handler(LyraError)
    async def lyra_error_handler(_request: Request, exc: LyraError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(f"http_{exc.status_code}", str(exc.detail)),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=_error_body(
                "validation_error",
                "Невалидный запрос",
                {"errors": jsonable_encoder(exc.errors())},
            ),
        )

    @app.middleware("http")
    async def trace_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        trace_id = request.headers.get("X-Trace-Id") or f"tr_{uuid.uuid4().hex}"
        structlog.contextvars.bind_contextvars(trace_id=trace_id)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("trace_id")
        response.headers["X-Trace-Id"] = trace_id
        return response

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def health_ready() -> JSONResponse:
        report = await readiness.readiness_report(get_settings())
        all_up = all(status == "up" for status in report.values())
        if not all_up:
            logger.warning("readiness_degraded", dependencies=report)
        return JSONResponse(
            status_code=200 if all_up else 503,
            content={"status": "ready" if all_up else "degraded", "dependencies": report},
        )

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
