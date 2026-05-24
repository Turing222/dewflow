"""SMS verification code service.

职责：生成、发送、校验短信验证码；管理发送频率限制。
边界：本模块不处理用户查找或 JWT 签发，仅负责验证码的生命周期。
"""

import logging
import secrets
import string

from backend.core.exceptions import app_bad_request
from backend.infra.redis import RedisClient

logger = logging.getLogger(__name__)

_SMS_CODE_PREFIX = "sms:"
_SMS_RATE_PREFIX = "sms_rate:"


class SMSService:
    """短信验证码服务（mock 模式下验证码仅记录到日志）。"""

    def __init__(
        self,
        redis_client: RedisClient,
        sms_code_expire_seconds: int,
        sms_code_rate_limit_seconds: int,
        sms_mock_mode: bool,
    ) -> None:
        self._redis_client = redis_client
        self._sms_code_expire_seconds = sms_code_expire_seconds
        self._sms_code_rate_limit_seconds = sms_code_rate_limit_seconds
        self._sms_mock_mode = sms_mock_mode

    async def _get_redis(self):
        return await self._redis_client.init()

    async def send_code(self, phone: str) -> str:
        """生成验证码并存入 Redis，mock 模式下仅写日志。

        Returns:
            生成的 6 位验证码。
        """
        redis = await self._get_redis()

        # 频率限制检查
        rate_key = f"{_SMS_RATE_PREFIX}{phone}"
        if await redis.get(rate_key):
            raise app_bad_request("发送过于频繁，请稍后再试", code="SMS_RATE_LIMITED")

        # 生成 6 位验证码
        code = "".join(secrets.choice(string.digits) for _ in range(6))

        # 存入 Redis（TTL 由配置决定）
        code_key = f"{_SMS_CODE_PREFIX}{phone}"
        await redis.set(code_key, code, ex=self._sms_code_expire_seconds)

        # 设置发送间隔限制
        await redis.set(rate_key, "1", ex=self._sms_code_rate_limit_seconds)

        # Mock 模式：记录日志
        if self._sms_mock_mode:
            logger.info("[SMS Mock] 验证码 phone=%s code=%s", phone, code)
        else:
            # TODO: 对接真实 SMS 服务商（阿里云/腾讯云）
            logger.info("[SMS] 验证码已发送至 phone=%s", phone)

        return code

    async def verify_code(self, phone: str, code: str) -> bool:
        """校验验证码，成功后删除（一次性使用）。

        Returns:
            True 表示验证通过，False 表示验证码错误或已过期。
        """
        redis = await self._get_redis()
        code_key = f"{_SMS_CODE_PREFIX}{phone}"
        stored = await redis.get(code_key)

        if stored is None:
            return False
        if isinstance(stored, bytes):
            stored = stored.decode()
        if stored != code:
            return False

        # 验证通过后删除，防止重复使用
        await redis.delete(code_key)
        return True
