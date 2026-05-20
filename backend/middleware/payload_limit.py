"""Payload size limit middleware."""

from starlette.types import ASGIApp, Receive, Scope, Send

from backend.core.constants import MAX_PAYLOAD_SIZE_BYTES

_TOO_LARGE = b'{"detail":"Payload Too Large"}'


class PayloadLimitMiddleware:
    """拦截超大请求体，防止 OOM 攻击。

    使用原生 ASGI 中间件而非 BaseHTTPMiddleware，
    避免 SSE 流式响应下 receive 链被干扰导致流中断。
    """

    def __init__(
        self, app: ASGIApp, max_payload_size: int = MAX_PAYLOAD_SIZE_BYTES
    ) -> None:
        self.app = app
        self.max_payload_size = max_payload_size

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length", b"").decode()

        if content_length:
            try:
                if int(content_length) > self.max_payload_size:
                    await self._send_too_large(send)
                    return
            except ValueError:
                pass

        method = scope.get("method", "")
        if method in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return

        content_type = headers.get(b"content-type", b"").decode().lower()
        if "multipart/form-data" in content_type:
            await self.app(scope, receive, send)
            return

        if "application/json" not in content_type:
            await self.app(scope, receive, send)
            return

        # Buffer JSON body to enforce size limit, then re-inject as single receive.
        body_parts: list[bytes] = []
        body_size = 0
        more_body = True
        while more_body:
            message = await receive()
            body = message.get("body", b"")
            more_body = message.get("more_body", False)
            body_size += len(body)
            if body_size > self.max_payload_size:
                await self._send_too_large(send)
                return
            body_parts.append(body)

        full_body = b"".join(body_parts)
        body_sent = False

        async def buffered_receive() -> dict[str, object]:
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {
                    "type": "http.request",
                    "body": full_body,
                    "more_body": False,
                }
            return await receive()

        await self.app(scope, buffered_receive, send)

    @staticmethod
    async def _send_too_large(send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    [b"content-type", b"application/json"],
                    [b"content-length", str(len(_TOO_LARGE)).encode()],
                ],
            }
        )
        await send({"type": "http.response.body", "body": _TOO_LARGE})
