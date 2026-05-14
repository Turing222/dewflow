"""Payload size limit middleware."""

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from backend.core.constants import MAX_PAYLOAD_SIZE_BYTES


class PayloadLimitMiddleware(BaseHTTPMiddleware):
    """拦截超大请求体，防止 OOM 攻击。"""

    def __init__(
        self, app, max_payload_size: int = MAX_PAYLOAD_SIZE_BYTES, **kwargs
    ) -> None:
        super().__init__(app, **kwargs)
        self.max_payload_size = max_payload_size

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > self.max_payload_size:
                    return JSONResponse(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        content={"detail": "Payload Too Large"},
                    )
            except ValueError:
                pass

        if request.method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)

        content_type = (request.headers.get("content-type") or "").lower()
        if "multipart/form-data" in content_type:
            # 文件上传大小由 Nginx client_max_body_size 限制，不在此缓冲
            return await call_next(request)

        if "application/json" not in content_type:
            # 非 JSON 请求体（如 text/plain）只依赖 Content-Length 检查，
            # 不缓冲 body 以避免内存占用
            return await call_next(request)

        body_parts: list[bytes] = []
        body_size = 0
        async for chunk in request.stream():
            body_size += len(chunk)
            if body_size > self.max_payload_size:
                return JSONResponse(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    content={"detail": "Payload Too Large"},
                )
            body_parts.append(chunk)

        body = b"".join(body_parts)
        # NOTE: Starlette Request._body / Request._receive are internal details
        # (tested on Starlette ≥0.37). Re-validate when upgrading Starlette.
        request._body = body

        async def receive() -> dict[str, object]:
            return {"type": "http.request", "body": body, "more_body": False}

        request._receive = receive
        return await call_next(request)
