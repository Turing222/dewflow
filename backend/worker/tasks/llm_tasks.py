"""LLM TaskIQ tasks.

职责：恢复 trace context、装配 worker 依赖，并调用 worker-side 生成 workflow。
边界：本模块不实现 provider 调用细节，也不直接散写数据库。
"""

import logging
import uuid
from typing import Any

from langfuse import observe

from backend.application.chat.worker_generation_workflow import (
    LLMGenerationWorkerWorkflow,
    StreamGenerationPayload,
)
from backend.infra.task_broker import broker
from backend.observability.trace_utils import trace_span, use_trace_context
from backend.services.unit_of_work import SQLAlchemyUnitOfWork
from backend.worker.dependencies import (
    get_worker_llm_service,
    get_worker_session_factory,
)

logger = logging.getLogger(__name__)


@broker.task(task_name="generate_llm_stream")
@observe(as_type="generation")
async def generate_llm_stream_task(
    generation_payload: dict[str, Any],
    channel: str,
    trace_context: dict[str, str] | None = None,
    assistant_message_id: str | None = None,
    user_id: str | None = None,
    idempotency_lock_key: str | None = None,
) -> None:
    """TaskIQ 入口：恢复 trace context 后执行流式生成。"""
    with use_trace_context(trace_context):
        await _generate_llm_stream_task(
            generation_payload=generation_payload,
            channel=channel,
            assistant_message_id=assistant_message_id,
            user_id=user_id,
            idempotency_lock_key=idempotency_lock_key,
        )


async def _generate_llm_stream_task(
    *,
    generation_payload: dict[str, Any],
    channel: str,
    assistant_message_id: str | None = None,
    user_id: str | None = None,
    idempotency_lock_key: str | None = None,
) -> None:
    logger.info("TaskIQ Worker 开始处理流式请求: %s", channel)

    with trace_span(
        "taskiq.llm_stream.setup",
        {
            "redis.channel": channel,
            "chat.assistant_message_id": assistant_message_id,
        },
    ):
        workflow = LLMGenerationWorkerWorkflow(
            uow=SQLAlchemyUnitOfWork(get_worker_session_factory()),
            llm_service=get_worker_llm_service(),
        )
        payload = StreamGenerationPayload(**generation_payload)
        assistant_uuid = (
            uuid.UUID(assistant_message_id) if assistant_message_id else None
        )
        user_uuid = uuid.UUID(user_id) if user_id else None

    await workflow.generate_stream(
        payload=payload,
        channel=channel,
        assistant_message_id=assistant_uuid,
        user_id=user_uuid,
        idempotency_lock_key=idempotency_lock_key,
    )
