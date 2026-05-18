"""LLM TaskIQ tasks.

职责：恢复 trace context、装配 worker 依赖，并调用 worker-side 生成 workflow。
边界：本模块不实现 provider 调用细节，也不直接散写数据库。
"""

import logging
import uuid

from backend.application.chat.worker_generation_workflow import (
    LLMGenerationWorkerWorkflow,
)
from backend.infra.redis import redis_client
from backend.infra.task_broker import broker
from backend.models.schemas.chat.payloads import GenerationPayload, GenerationResult
from backend.observability.langfuse_utils import (
    langfuse_generation,
    set_langfuse_trace_metadata,
)
from backend.observability.trace_utils import (
    trace_span,
    use_trace_context,
)
from backend.services.unit_of_work import SQLAlchemyUnitOfWork
from backend.worker.dependencies import (
    get_worker_llm_service,
    get_worker_rag_planning_service,
    get_worker_rag_service,
    get_worker_session_factory,
)

logger = logging.getLogger(__name__)


# ── Streaming ──────────────────────────────────────────────────────


@broker.task(task_name="generate_llm_stream")
async def generate_llm_stream_task(
    generation_payload: dict,
    channel: str,
    trace_context: dict[str, str] | None = None,
    assistant_message_id: str | None = None,
    user_id: str | None = None,
    idempotency_lock_key: str | None = None,
) -> None:
    """TaskIQ 入口：恢复 trace context 后执行流式生成。"""
    with use_trace_context(trace_context):
        payload = GenerationPayload(**generation_payload)
        with set_langfuse_trace_metadata(
            user_id=user_id,
            session_id=payload.session_id,
            tags=["chat_api", "worker", "stream"],
        ):
            with langfuse_generation(
                name="generate_llm_stream",
                input_payload=generation_payload,
            ):
                await _generate_llm_stream_task(
                    payload=payload,
                    channel=channel,
                    assistant_message_id=assistant_message_id,
                    user_id=user_id,
                    idempotency_lock_key=idempotency_lock_key,
                )


async def _generate_llm_stream_task(
    *,
    payload: GenerationPayload,
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
        llm_service = get_worker_llm_service()
        workflow = LLMGenerationWorkerWorkflow(
            uow=SQLAlchemyUnitOfWork(get_worker_session_factory()),
            redis_client=redis_client,
            llm_service=llm_service,
            rag_service=get_worker_rag_service(llm_service=llm_service),
            rag_planning_service=get_worker_rag_planning_service(),
        )
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


# ── Non-Streaming ──────────────────────────────────────────────────


@broker.task(task_name="generate_llm_nonstream")
async def generate_llm_nonstream_task(
    generation_payload: dict,
    trace_context: dict[str, str] | None = None,
    assistant_message_id: str | None = None,
    user_id: str | None = None,
    idempotency_lock_key: str | None = None,
) -> GenerationResult:
    """TaskIQ 入口：恢复 trace context 后执行非流式生成，返回结果 dict。"""
    with use_trace_context(trace_context):
        payload = GenerationPayload(**generation_payload)
        with set_langfuse_trace_metadata(
            user_id=user_id,
            session_id=payload.session_id,
            tags=["chat_api", "worker", "non-stream"],
        ):
            with langfuse_generation(
                name="generate_llm_nonstream",
                input_payload=generation_payload,
            ):
                return await _generate_llm_nonstream_task(
                    payload=payload,
                    assistant_message_id=assistant_message_id,
                    user_id=user_id,
                    idempotency_lock_key=idempotency_lock_key,
                )


async def _generate_llm_nonstream_task(
    *,
    payload: GenerationPayload,
    assistant_message_id: str | None = None,
    user_id: str | None = None,
    idempotency_lock_key: str | None = None,
) -> GenerationResult:
    logger.info(
        "TaskIQ Worker 开始处理非流式请求: message_id=%s",
        assistant_message_id,
    )

    with trace_span(
        "taskiq.llm_nonstream.setup",
        {"chat.assistant_message_id": assistant_message_id},
    ):
        llm_service = get_worker_llm_service()
        workflow = LLMGenerationWorkerWorkflow(
            uow=SQLAlchemyUnitOfWork(get_worker_session_factory()),
            redis_client=redis_client,
            llm_service=llm_service,
            rag_service=get_worker_rag_service(llm_service=llm_service),
            rag_planning_service=get_worker_rag_planning_service(),
        )
        assistant_uuid = (
            uuid.UUID(assistant_message_id) if assistant_message_id else None
        )
        user_uuid = uuid.UUID(user_id) if user_id else None

    return await workflow.generate_nonstream(
        payload=payload,
        assistant_message_id=assistant_uuid,
        user_id=user_uuid,
        idempotency_lock_key=idempotency_lock_key,
    )
