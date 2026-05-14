"""Redis client singleton.

职责：为应用代码提供按需初始化的主 Redis 连接。
边界：TaskIQ broker 使用独立配置，不通过本模块创建。
副作用：连接会在首次 init 时建立，应用关闭时应调用 close。
"""

import asyncio

import redis.asyncio as redis

from backend.config.settings import settings


class RedisClient:
    """按需创建并缓存 redis.asyncio 客户端。"""

    def __init__(self) -> None:
        self.client: redis.Redis | None = None
        self._init_lock = asyncio.Lock()

    async def init(self) -> redis.Redis:
        if self.client is not None:
            return self.client
        async with self._init_lock:
            if self.client is not None:
                return self.client
            self.client = redis.from_url(
                settings.redis_url,
                decode_responses=True,
            )
            return self.client

    async def close(self) -> None:
        if self.client:
            await self.client.close()
            self.client = None


redis_client = RedisClient()


async def safe_release_lock(
    redis_client: redis.Redis, lock_key: str, lock_token: str
) -> None:
    """安全释放 Redis 锁（Lua 脚本）。"""
    script = """
    if redis.call("get",KEYS[1]) == ARGV[1] then
        return redis.call("del",KEYS[1])
    else
        return 0
    end
    """
    await redis_client.eval(script, 1, lock_key, lock_token)  # type: ignore[invalid-await]  # redis-py lacks async type stubs for eval
