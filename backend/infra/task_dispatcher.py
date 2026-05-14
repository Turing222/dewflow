"""TaskIQ dispatcher — the sole Web → Worker task boundary.

职责：封装 TaskIQ Redis wire-format 投递，让 Web workflow 只依赖 AbstractTaskDispatcher Protocol。
边界：本模块不 import worker.tasks.*，也不依赖 TaskIQ Python 包，避免 Web 镜像安装 Worker 运行时依赖。
副作用：投递任务时会连接 TaskIQ Redis 队列，非流式任务会轮询 Redis result backend。
"""

import asyncio
import json
import logging
import pickle
from typing import Any
from uuid import uuid4

import redis.asyncio as redis

from backend.config.ai_settings import ai_settings
from backend.config.settings import settings
from backend.contracts.interfaces import AbstractTaskDispatcher
from backend.models.schemas.chat.payloads import GenerationResult

logger = logging.getLogger(__name__)

# ── Task names (must match task_name= in worker task decorators) ───
TASK_STREAM = "generate_llm_stream"
TASK_NONSTREAM = "generate_llm_nonstream"
TASK_INGESTION = "ingest_knowledge_file"
TASKIQ_QUEUE_NAME = "taskiq"
TASK_RESULT_POLL_INTERVAL_SECONDS = 0.1


class TaskDispatcher(AbstractTaskDispatcher):
    """TaskIQ Redis wire-format 任务投递实现。"""

    def __init__(self) -> None:
        self._redis_url = settings.taskiq_redis_url
        self._redis_client: redis.Redis | None = None

    async def _get_redis(self) -> redis.Redis:
        """Lazily create and cache the Redis connection for TaskIQ queue + result backend."""
        if self._redis_client is None:
            self._redis_client = redis.from_url(self._redis_url, decode_responses=False)
        return self._redis_client

    async def _send_task(self, task_name: str, *args: Any) -> str:
        task_id = uuid4().hex
        message = self._build_taskiq_message(task_id=task_id, task_name=task_name, args=args)
        redis_client = await self._get_redis()
        await redis_client.lpush(TASKIQ_QUEUE_NAME, message)  # type: ignore[invalid-await]  # redis-py lacks async type stubs
        return task_id

    # NOTE: The 6-key structure below (task_id, task_name, labels, labels_types,
    # args, kwargs) is the TaskIQ 0.12 ListQueueBroker wire format. If TaskIQ
    # adds a required field (e.g. version or priority), worker deserialization
    # will break silently — CI won't catch it because web and worker use separate
    # extras groups. Consider adding a CI smoke test that verifies web-dispatched
    # messages are consumable by the worker.
    @staticmethod
    def _build_taskiq_message(
        *,
        task_id: str,
        task_name: str,
        args: tuple[Any, ...],
    ) -> bytes:
        message = {
            "task_id": task_id,
            "task_name": task_name,
            "labels": {},
            "labels_types": {},
            "args": list(args),
            "kwargs": {},
        }
        return json.dumps(message, ensure_ascii=True).encode()

    async def _wait_result(self, task_id: str, timeout: float) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + timeout
        redis_client = await self._get_redis()
        # NOTE: pickle.loads deserializes TaskIQ's internal TaskiqResult format
        # (is_err / return_value fields). This format is not a public API —
        # upgrading TaskIQ may change the serialization format.
        while asyncio.get_running_loop().time() < deadline:
            raw_result = await redis_client.get(task_id)
            if raw_result is not None:
                result = pickle.loads(raw_result)  # noqa: S301
                if result.get("is_err"):
                    raise RuntimeError("TaskIQ task failed")
                return_value = result.get("return_value")
                if not isinstance(return_value, dict):
                    raise RuntimeError("TaskIQ task returned an invalid result")
                return return_value
            await asyncio.sleep(TASK_RESULT_POLL_INTERVAL_SECONDS)
        raise TimeoutError("TaskIQ task result timed out")

    async def enqueue_stream(
        self,
        generation_payload: dict[str, Any],
        channel: str,
        trace_context: dict[str, str] | None = None,
        assistant_message_id: str | None = None,
        user_id: str | None = None,
        idempotency_lock_key: str | None = None,
    ) -> None:
        await self._send_task(
            TASK_STREAM,
            generation_payload,
            channel,
            trace_context,
            assistant_message_id,
            user_id,
            idempotency_lock_key,
        )

    async def enqueue_nonstream(
        self,
        generation_payload: dict[str, Any],
        trace_context: dict[str, str] | None = None,
        assistant_message_id: str | None = None,
        user_id: str | None = None,
        idempotency_lock_key: str | None = None,
    ) -> GenerationResult:
        task_id = await self._send_task(
            TASK_NONSTREAM,
            generation_payload,
            trace_context,
            assistant_message_id,
            user_id,
            idempotency_lock_key,
        )
        result = await self._wait_result(
            task_id,
            timeout=ai_settings.CHAT_STREAM_FIRST_MESSAGE_TIMEOUT_SECONDS + 300
        )
        return GenerationResult.model_validate(result)

    async def enqueue_ingestion(
        self,
        file_id: str,
        task_id: str | None = None,
        trace_context: dict[str, str] | None = None,
    ) -> None:
        await self._send_task(
            TASK_INGESTION,
            file_id,
            task_id,
            trace_context,
        )
