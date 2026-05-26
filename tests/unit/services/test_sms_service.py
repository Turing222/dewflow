"""SMSService unit tests.

职责：验证验证码生成（secrets.choice）、Redis 存取和频率限制；
边界：使用 mock redis_client，不连接真实 Redis；副作用：无。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.exceptions import AppException
from backend.services.sms_service import SMSService

pytestmark = pytest.mark.asyncio


def _make_redis_mock() -> SimpleNamespace:
    """Build a mock Redis instance returned by redis_client.init()."""
    redis = SimpleNamespace(
        get=AsyncMock(return_value=None),
        set=AsyncMock(),
        delete=AsyncMock(),
    )
    return redis


def _make_redis_client(redis: SimpleNamespace | None = None) -> AsyncMock:
    """Build a mock RedisClient whose init() returns the given redis instance."""
    if redis is None:
        redis = _make_redis_mock()
    client = AsyncMock()
    client.init = AsyncMock(return_value=redis)
    return client


def make_sms_service(
    *,
    sms_code_expire_seconds: int = 300,
    sms_code_rate_limit_seconds: int = 60,
    sms_mock_mode: bool = True,
    redis: SimpleNamespace | None = None,
) -> SMSService:
    redis_client = _make_redis_client(redis)
    return SMSService(
        redis_client=redis_client,
        sms_code_expire_seconds=sms_code_expire_seconds,
        sms_code_rate_limit_seconds=sms_code_rate_limit_seconds,
        sms_mock_mode=sms_mock_mode,
    )


async def test_send_code_generates_6_digit_code() -> None:
    redis = _make_redis_mock()
    service = make_sms_service(redis=redis)

    code = await service.send_code("13800138000")

    assert len(code) == 6
    assert code.isdigit()


async def test_send_code_stores_in_redis_with_ttl() -> None:
    redis = _make_redis_mock()
    service = make_sms_service(
        redis=redis,
        sms_code_expire_seconds=300,
        sms_code_rate_limit_seconds=60,
    )

    code = await service.send_code("13800138000")

    # code stored with TTL
    code_key = "sms:13800138000"
    redis.set.assert_any_call(code_key, code, ex=300)
    # rate-limit key set
    rate_key = "sms_rate:13800138000"
    redis.set.assert_any_call(rate_key, "1", ex=60)


async def test_send_code_respects_rate_limit() -> None:
    redis = _make_redis_mock()
    redis.get.return_value = "1"  # rate-limit key exists
    service = make_sms_service(redis=redis)

    with pytest.raises(AppException) as exc_info:
        await service.send_code("13800138000")

    assert exc_info.value.code == "SMS_RATE_LIMITED"
    redis.set.assert_not_awaited()


async def test_send_code_mock_mode_logs_without_sending() -> None:
    redis = _make_redis_mock()
    service = make_sms_service(redis=redis, sms_mock_mode=True)

    code = await service.send_code("13800138000")

    assert len(code) == 6
    # In mock mode, code is returned and logged — no third-party call.


async def test_verify_code_success_deletes_key() -> None:
    redis = _make_redis_mock()
    service = make_sms_service(redis=redis, sms_mock_mode=True)

    code = await service.send_code("13800138000")

    # Simulate stored code
    redis.get.return_value = code

    result = await service.verify_code("13800138000", code)

    assert result is True
    redis.delete.assert_awaited_once_with("sms:13800138000")


async def test_verify_code_wrong_code_returns_false() -> None:
    redis = _make_redis_mock()
    service = make_sms_service(redis=redis, sms_mock_mode=True)

    await service.send_code("13800138000")

    redis.get.return_value = "999999"
    result = await service.verify_code("13800138000", "000000")

    assert result is False
    redis.delete.assert_not_awaited()


async def test_verify_code_expired_returns_false() -> None:
    redis = _make_redis_mock()
    redis.get.return_value = None
    service = make_sms_service(redis=redis)

    result = await service.verify_code("13800138000", "123456")

    assert result is False
    redis.delete.assert_not_awaited()


async def test_verify_code_handles_bytes_from_redis() -> None:
    redis = _make_redis_mock()
    service = make_sms_service(redis=redis, sms_mock_mode=True)

    code = await service.send_code("13800138000")

    # Redis may return bytes
    redis.get.return_value = code.encode()

    result = await service.verify_code("13800138000", code)

    assert result is True
    redis.delete.assert_awaited_once()
