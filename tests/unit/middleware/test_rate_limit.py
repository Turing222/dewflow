from __future__ import annotations

from fastapi import Depends, FastAPI, Request
from httpx import ASGITransport, AsyncClient

from backend.core.exception_handlers import setup_exception_handlers
from backend.middleware.rate_limit import RateLimiter


class FakeRedis:
    def __init__(self, result: list[int]):
        self.result = result
        self.calls: list[tuple] = []

    async def eval(self, *args):
        self.calls.append(args)
        return self.result


async def _client(fake_redis: FakeRedis):
    app = FastAPI()
    setup_exception_handlers(app)
    limiter = RateLimiter(times=2, seconds=60)

    @app.get("/limited", dependencies=[Depends(limiter)])
    async def limited(request: Request):
        return {"rate_limit": request.state.rate_limit}

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test"), fake_redis


async def test_rate_limit_records_allowed_result(monkeypatch):
    fake_redis = FakeRedis([1, 1])

    async def init_redis():
        return fake_redis

    monkeypatch.setattr("backend.middleware.rate_limit.redis_client.init", init_redis)
    client, _ = await _client(fake_redis)

    async with client:
        response = await client.get("/limited")

    assert response.status_code == 200
    assert response.json() == {
        "rate_limit": {
            "rate_limit.allowed": True,
            "rate_limit.current_count": 1,
        }
    }
    assert fake_redis.calls


async def test_rate_limit_rejects_when_window_is_full(monkeypatch):
    fake_redis = FakeRedis([0, 2])

    async def init_redis():
        return fake_redis

    monkeypatch.setattr("backend.middleware.rate_limit.redis_client.init", init_redis)
    client, _ = await _client(fake_redis)

    async with client:
        response = await client.get("/limited")

    assert response.status_code == 429
    assert response.json()["error_code"] == "TOO_MANY_REQUESTS"
    assert response.json()["details"] == {
        "limit_count": 2,
        "current_count": 2,
    }


async def test_rate_limit_uses_compact_unique_members(monkeypatch):
    fake_redis = FakeRedis([1, 1])
    random_values = iter([b"abcd", b"efgh"])

    async def init_redis():
        return fake_redis

    monkeypatch.setattr("backend.middleware.rate_limit.redis_client.init", init_redis)
    monkeypatch.setattr("backend.middleware.rate_limit.time.time", lambda: 123.456)
    monkeypatch.setattr(
        "backend.middleware.rate_limit.os.urandom",
        lambda size: next(random_values),
    )
    client, _ = await _client(fake_redis)

    async with client:
        assert (await client.get("/limited")).status_code == 200
        assert (await client.get("/limited")).status_code == 200

    members = [call[6] for call in fake_redis.calls]
    assert members == ["123456:61626364", "123456:65666768"]
    assert all(len(member) == 15 for member in members)
