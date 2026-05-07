"""Infrastructure dependencies.

职责：提供与基础设施（如 Redis、数据库连接池等）相关的 FastAPI 依赖注入。
边界：封装具体的初始化细节，向上层暴露干净的客户端对象。
"""

from collections.abc import AsyncGenerator

import redis.asyncio as redis

from backend.infra.redis import redis_client


async def get_redis() -> AsyncGenerator[redis.Redis, None]:
    """获取 Redis 客户端单例的依赖提供者。"""
    client = await redis_client.init()
    yield client
