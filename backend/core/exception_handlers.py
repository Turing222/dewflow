"""FastAPI global exception handlers.

职责：将 AppException / HTTPException / RequestValidationError 映射为统一 JSON 响应。
边界：依赖 FastAPI，仅供 web 层使用——worker 不应加载此模块。
"""

import logging
import time

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.core.exceptions import AppException

logger = logging.getLogger(__name__)


def _trace_response_headers(request: Request) -> dict[str, str]:
    headers: dict[str, str] = {}
    request_id = getattr(request.state, "request_id", None)
    trace_id = getattr(request.state, "trace_id", None)
    process_start = getattr(request.state, "process_start", None)

    if request_id:
        headers["X-Request-ID"] = str(request_id)
    if trace_id:
        headers["X-Trace-ID"] = str(trace_id)
    if isinstance(process_start, int | float):
        headers["X-Process-Time"] = (
            f"{(time.perf_counter() - process_start) * 1000:.2f}ms"
        )
    return headers


def setup_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器，保持错误响应结构一致。"""

    @app.exception_handler(AppException)
    async def app_exception_handler(
        request: Request,
        exc: AppException,
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)

        logger.warning(
            "AppException: code=%s message=%s request_id=%s",
            exc.code,
            exc.message,
            request_id,
        )

        return JSONResponse(
            status_code=exc.status_code,
            content=jsonable_encoder(
                {
                    "error_code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                    "request_id": request_id,
                }
            ),
            headers=_trace_response_headers(request),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        detail = exc.detail

        logger.warning(
            "HTTPException: status_code=%s detail=%s request_id=%s",
            exc.status_code,
            detail,
            request_id,
        )

        return JSONResponse(
            status_code=exc.status_code,
            content=jsonable_encoder(
                {
                    "error_code": f"HTTP_{exc.status_code}",
                    "message": detail if isinstance(detail, str) else "请求失败",
                    "details": detail if isinstance(detail, dict) else {},
                    "request_id": request_id,
                }
            ),
            headers={
                **_trace_response_headers(request),
                **(getattr(exc, "headers", None) or {}),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)

        logger.warning(
            "RequestValidationError: request_id=%s errors=%s",
            request_id,
            exc.errors(),
        )

        return JSONResponse(
            status_code=422,
            content=jsonable_encoder(
                {
                    "error_code": "REQUEST_VALIDATION_ERROR",
                    "message": "请求参数校验失败",
                    "details": {"errors": exc.errors()},
                    "request_id": request_id,
                }
            ),
            headers=_trace_response_headers(request),
        )

    @app.exception_handler(Exception)
    async def unexpected_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)

        logger.exception(
            "Unexpected exception: type=%s request_id=%s",
            exc.__class__.__name__,
            request_id,
        )

        return JSONResponse(
            status_code=500,
            content={
                "error_code": "INTERNAL_SERVER_ERROR",
                "message": "服务器内部错误",
                "details": {},
                "request_id": request_id,
            },
            headers=_trace_response_headers(request),
        )
