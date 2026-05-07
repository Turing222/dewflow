"""TaskIQ dispatcher — the sole Web → Worker task boundary.

职责：封装所有 TaskIQ .kiq() 调用，让 Web workflow 只依赖 AbstractTaskDispatcher Protocol。
边界：本模块是 worker.tasks.* 被 Web 侧引用的唯一合法入口。
      使用 AsyncKicker 按 task_name 字符串投递，不直接 import worker 任务模块，
      避免 Web 侧被迫加载 langfuse / openai 等 AI 依赖。
"""

import logging
from typing import Any

from taskiq.kicker import AsyncKicker

from backend.config.ai_settings import ai_settings
from backend.contracts.interfaces import AbstractTaskDispatcher
from backend.infra.task_broker import broker
from backend.models.schemas.chat.payloads import GenerationResult

logger = logging.getLogger(__name__)

# ── Task names (must match task_name= in worker task decorators) ───
TASK_STREAM = "generate_llm_stream"
TASK_NONSTREAM = "generate_llm_nonstream"
TASK_INGESTION = "ingest_knowledge_file"


class TaskDispatcher(AbstractTaskDispatcher):
    """TaskIQ 任务投递实现。

    所有 Web workflow 通过此类投递异步任务到 Worker，
    使用 AsyncKicker 按 task_name 字符串直接构造消息，
    不依赖具体的 TaskIQ task 对象或 worker 模块。
    """

    def __init__(self) -> None:
        self._kickers: dict[str, AsyncKicker] = {}

    def _get_kicker(self, task_name: str) -> AsyncKicker:
        if task_name not in self._kickers:
            self._kickers[task_name] = AsyncKicker(
                task_name=task_name, broker=broker, labels={}
            )
        return self._kickers[task_name]

    async def enqueue_stream(
        self,
        generation_payload: dict[str, Any],
        channel: str,
        trace_context: dict[str, str] | None = None,
        assistant_message_id: str | None = None,
        user_id: str | None = None,
        idempotency_lock_key: str | None = None,
    ) -> None:
        kicker = self._get_kicker(TASK_STREAM)
        await kicker.kiq(
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
        kicker = self._get_kicker(TASK_NONSTREAM)
        task = await kicker.kiq(
            generation_payload,
            trace_context,
            assistant_message_id,
            user_id,
            idempotency_lock_key,
        )
        taskiq_result = await task.wait_result(
            timeout=ai_settings.CHAT_STREAM_FIRST_MESSAGE_TIMEOUT_SECONDS + 300
        )
        return GenerationResult.model_validate(taskiq_result.return_value)

    async def enqueue_ingestion(
        self,
        file_id: str,
        task_id: str | None = None,
        trace_context: dict[str, str] | None = None,
    ) -> None:
        kicker = self._get_kicker(TASK_INGESTION)
        await kicker.kiq(
            file_id,
            task_id,
            trace_context,
        )
