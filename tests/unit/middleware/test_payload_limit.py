from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from backend.middleware.payload_limit import PayloadLimitMiddleware


@pytest.fixture
async def client():
    inner_app = FastAPI()

    @inner_app.post("/echo-size")
    async def echo_size(request: Request):
        body = await request.body()
        return {"size": len(body), "body": body.decode("utf-8")}

    app = PayloadLimitMiddleware(inner_app, max_payload_size=5)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _chunked_body() -> AsyncIterator[bytes]:
    yield b"abc"
    yield b"def"


@pytest.mark.asyncio
async def test_payload_limit_rejects_chunked_body_without_content_length(client):
    response = await client.post("/echo-size", content=_chunked_body())

    assert response.status_code == 413
    assert response.json() == {"detail": "Payload Too Large"}


@pytest.mark.asyncio
async def test_payload_limit_replays_allowed_body(client):
    response = await client.post("/echo-size", content=b"hello")

    assert response.status_code == 200
    assert response.json() == {"size": 5, "body": "hello"}
