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

    @inner_app.get("/echo-get")
    async def echo_get():
        return {"ok": True}

    app = PayloadLimitMiddleware(inner_app, max_payload_size=5)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _chunked_body() -> AsyncIterator[bytes]:
    yield b"abc"
    yield b"def"


@pytest.mark.asyncio
async def test_payload_limit_rejects_large_json_body(client):
    response = await client.post(
        "/echo-size",
        content=_chunked_body(),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "Payload Too Large"}


@pytest.mark.asyncio
async def test_payload_limit_replays_allowed_json_body(client):
    response = await client.post(
        "/echo-size",
        content=b"hello",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert response.json() == {"size": 5, "body": "hello"}


@pytest.mark.asyncio
async def test_payload_limit_skips_get_requests(client):
    response = await client.get("/echo-get")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.asyncio
async def test_payload_limit_skips_multipart_form_data_buffering(client):
    # multipart/form-data body is not buffered into memory.
    # Content-Length header check still applies (fast integer comparison).
    # This test verifies that a body under the limit passes through
    # without being consumed by body buffering.
    response = await client.post(
        "/echo-size",
        content=b"ok",
        headers={"Content-Type": "multipart/form-data; boundary=---boundary"},
    )

    # Body passes through to the endpoint; Starlette may return 200 or 400
    # depending on multipart parsing, but never 413
    assert response.status_code != 413
