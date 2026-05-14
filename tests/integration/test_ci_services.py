"""CI service connectivity tests.

职责：验证集成测试环境中的 PostgreSQL 和 Redis 可达，不执行迁移或业务数据写入。
边界：仅做基础设施连通性探测，真实业务 API 行为由其他集成测试覆盖。
"""

from __future__ import annotations

import os

import pytest
import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.config.settings import settings


def _is_ci() -> bool:
    return os.getenv("CI", "").strip().lower() == "true"


@pytest.mark.asyncio
async def test_ci_postgres_service_is_reachable() -> None:
    engine = create_async_engine(
        settings.database_url,
        connect_args=settings.database_connect_args,
        pool_pre_ping=True,
    )
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT 1"))
            assert result.scalar_one() == 1
    except Exception as exc:
        if _is_ci():
            raise
        pytest.skip(f"PostgreSQL service is not reachable: {exc}")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ci_redis_service_is_reachable() -> None:
    client = redis.from_url(settings.taskiq_redis_url, decode_responses=True)
    try:
        assert await client.ping() is True
    except Exception as exc:
        if _is_ci():
            raise
        pytest.skip(f"Redis service is not reachable: {exc}")
    finally:
        await client.aclose()
